
from functools import wraps

from django.contrib import messages
from django.contrib.auth import login, logout, get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Prefetch, Sum
from django.forms import modelform_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .models import (
    Campeonato,
    Equipo,
    Estadistica,
    EventoPartido,
    Jugador,
    Partido,
    InscripcionEquipo,
    SolicitudCampeonato,
)

User = get_user_model()


# =========================================================
# CONTROL DE PERMISOS
# =========================================================

def admin_required(vista):
    """Permite el acceso únicamente a administradores autenticados."""

    @wraps(vista)
    @login_required(login_url="login")
    def comprobar_permisos(request, *args, **kwargs):

        if not request.user.is_staff:
            messages.error(
                request,
                "No tienes permisos para acceder a esa sección."
            )
            return redirect("index")

        return vista(request, *args, **kwargs)

    return comprobar_permisos


# =========================================================
# FUNCIONES AUXILIARES
# =========================================================

def _guardar_modelo(
    request,
    modelo,
    campos,
    plantilla,
    contexto,
    nombre_url,
    instancia=None,
):
    """Crea o actualiza registros mediante formularios de Django."""

    Formulario = modelform_factory(modelo, fields=campos)

    form = Formulario(
        request.POST or None,
        instance=instancia
    )

    if request.method == "POST" and form.is_valid():

        try:
            with transaction.atomic():
                form.save()

            messages.success(
                request,
                "Registro guardado correctamente."
            )

            return redirect(nombre_url)

        except IntegrityError:
            messages.error(
                request,
                "No se pudo guardar el registro. "
                "Comprueba los datos y las relaciones existentes."
            )

    contexto.update({
        "form": form,
        "objeto": instancia,
        "editando": instancia is not None,
    })

    return render(request, plantilla, contexto)


def _eliminar_modelo(request, objeto, nombre_url, descripcion):
    """Elimina un registro y controla errores de integridad."""

    try:
        with transaction.atomic():
            objeto.delete()

        messages.success(
            request,
            f"{descripcion} eliminado correctamente."
        )

    except IntegrityError:
        messages.error(
            request,
            f"No se pudo eliminar {descripcion.lower()} "
            "porque tiene registros relacionados."
        )

    return redirect(nombre_url)


# =========================================================
# CONTEXTO DEL INICIO
# =========================================================

def _contexto_inicio():
    """Prepara los datos generales para los paneles de inicio."""

    resumen = Estadistica.objects.aggregate(
        total_goles=Sum("goles"),
        total_asistencias=Sum("asistencias"),
    )

    total_jugadores_estadisticas = (
        Estadistica.objects
        .values("id_jugador")
        .distinct()
        .count()
    )

    goleadores = (
        Estadistica.objects
        .values(
            "id_jugador",
            "id_jugador__nombre",
            "id_jugador__apellido",
            "id_jugador__id_equipo__nombre",
        )
        .annotate(goles=Sum("goles"))
        .filter(goles__gt=0)
        .order_by("-goles", "id_jugador__apellido")[:5]
    )

    asistidores = (
        Estadistica.objects
        .values(
            "id_jugador",
            "id_jugador__nombre",
            "id_jugador__apellido",
            "id_jugador__id_equipo__nombre",
        )
        .annotate(asistencias=Sum("asistencias"))
        .filter(asistencias__gt=0)
        .order_by("-asistencias", "id_jugador__apellido")[:5]
    )

    sanciones_registradas = (
        Estadistica.objects
        .select_related("id_jugador", "id_partido")
        .filter(
            Q(tarjetas_amarillas__gt=0)
            | Q(tarjetas_rojas__gt=0)
        )
        .order_by(
            "-id_partido__fecha",
            "-id_partido__hora"
        )[:10]
    )

    return {
        "total_campeonatos": Campeonato.objects.count(),
        "total_equipos": Equipo.objects.count(),
        "total_jugadores": Jugador.objects.count(),
        "total_partidos": Partido.objects.count(),

        "campeonato_activo": Campeonato.objects.first(),

        "equipos": (
            Equipo.objects
            .select_related("id_campeonato", "usuario_delegado")
            .order_by("nombre")
        ),

        "partidos": (
            Partido.objects
            .select_related(
                "equipo_local",
                "equipo_visitante",
                "id_campeonato",
            )
            .order_by("-fecha", "-hora")
        ),

        "total_goles": resumen["total_goles"] or 0,
        "total_asistencias": resumen["total_asistencias"] or 0,

        "total_jugadores_estadisticas": (
            total_jugadores_estadisticas
        ),

        "goleadores": goleadores,
        "asistidores": asistidores,
        "sanciones": sanciones_registradas,
    }


# =========================================================
# INICIO DE DELEGADOS
# =========================================================

@never_cache
def index(request):
    """Página principal de CHAMPMANAGER."""

    if request.user.is_authenticated and request.user.is_staff:
        return redirect("indexadmin")

    contexto = _contexto_inicio()

    if request.user.is_authenticated:

        equipos_usuario = Equipo.objects.filter(
            usuario_delegado=request.user
        )

        contexto["equipos"] = (
            equipos_usuario
            .select_related("id_campeonato", "usuario_delegado")
            .order_by("nombre")
        )

        contexto["total_equipos"] = equipos_usuario.count()

        contexto["total_jugadores"] = Jugador.objects.filter(
            id_equipo__usuario_delegado=request.user
        ).count()

        if not equipos_usuario.exists():
            messages.info(
                request,
                "¡Bienvenido a CHAMPMANAGER! Todavía no tienes equipos. "
                "Crea tu primer equipo para comenzar a registrar jugadores."
            )

    return render(request, "index.html", contexto)


# =========================================================
# INICIO EXCLUSIVO DEL ADMINISTRADOR
# =========================================================

@admin_required
@never_cache
def indexadmin(request):
    """Página principal exclusiva del administrador."""

    contexto = _contexto_inicio()

    return render(request, "indexadmin.html", contexto)


# =========================================================
# CAMPEONATOS
# =========================================================

@login_required(login_url="login")
def lista_campeonatos(request):
    """Muestra todos los campeonatos y las inscripciones del usuario."""

    campeonatos = list(
        Campeonato.objects
        .annotate(
            total_equipos=Count(
                "inscripciones__equipo",
                distinct=True
            )
        )
        .order_by("-fecha_inicio")
    )

    equipos_delegado = Equipo.objects.none()

    if not request.user.is_staff:

        equipos_delegado = Equipo.objects.filter(
            usuario_delegado=request.user
        ).order_by("nombre")

        for campeonato in campeonatos:

            campeonato.equipos_inscritos_usuario = set(
                InscripcionEquipo.objects.filter(
                    equipo__in=equipos_delegado,
                    campeonato=campeonato
                ).values_list("equipo_id", flat=True)
            )

            campeonato.equipos_pendientes_usuario = set(
                SolicitudCampeonato.objects.filter(
                    equipo__in=equipos_delegado,
                    campeonato=campeonato,
                    estado="pendiente"
                ).values_list("equipo_id", flat=True)
            )

    contexto = {
        "campeonatos": campeonatos,
        "equipos_delegado": equipos_delegado,

        "total_campeonatos": Campeonato.objects.count(),

        "total_en_curso": Campeonato.objects.filter(
            Q(estado__iexact="en_curso")
            | Q(estado__iexact="en curso")
        ).count(),

        "total_planificados": Campeonato.objects.filter(
            Q(estado__iexact="planificacion")
            | Q(estado__iexact="planificación")
            | Q(estado__iexact="planificado")
        ).count(),

        "total_finalizados": Campeonato.objects.filter(
            estado__iexact="finalizado"
        ).count(),
    }

    return render(request, "campeonatos.html", contexto)


@login_required(login_url="login")
@require_POST
def solicitar_campeonato(request, pk):
    """Permite al delegado solicitar la inscripción de uno de sus equipos."""

    if request.user.is_staff:
        messages.error(
            request,
            "Los administradores no necesitan solicitar inscripciones."
        )
        return redirect("campeonatos")

    campeonato = get_object_or_404(Campeonato, pk=pk)

    equipo_id = request.POST.get("equipo")

    if not equipo_id:
        messages.error(
            request,
            "Debes seleccionar un equipo."
        )
        return redirect("campeonatos")

    equipo = get_object_or_404(
        Equipo,
        pk=equipo_id,
        usuario_delegado=request.user
    )

    if InscripcionEquipo.objects.filter(
        equipo=equipo,
        campeonato=campeonato
    ).exists():
        messages.warning(
            request,
            "Este equipo ya participa en el campeonato."
        )
        return redirect("campeonatos")

    solicitud = SolicitudCampeonato.objects.filter(
        equipo=equipo,
        campeonato=campeonato
    ).first()

    if solicitud:

        if solicitud.estado == "pendiente":
            messages.warning(
                request,
                "Ya existe una solicitud pendiente para este equipo."
            )
            return redirect("campeonatos")

        if solicitud.estado == "aprobada":
            messages.warning(
                request,
                "Esta solicitud ya fue aprobada."
            )
            return redirect("campeonatos")

        solicitud.estado = "pendiente"
        solicitud.usuario = request.user
        solicitud.fecha_solicitud = timezone.now()
        solicitud.save()

    else:
        SolicitudCampeonato.objects.create(
            equipo=equipo,
            campeonato=campeonato,
            usuario=request.user,
            estado="pendiente"
        )

    messages.success(
        request,
        f"Solicitud enviada correctamente para el equipo {equipo.nombre}."
    )

    return redirect("campeonatos")


# =========================================================
# SOLICITUDES: PANEL DEL ADMINISTRADOR
# =========================================================

@admin_required
def lista_solicitudes(request):
    """Muestra las solicitudes de inscripción de los delegados."""

    solicitudes = (
        SolicitudCampeonato.objects
        .select_related(
            "equipo",
            "campeonato",
            "usuario"
        )
        .order_by("-fecha_solicitud")
    )

    contexto = {
        "solicitudes": solicitudes,
        "total_solicitudes": solicitudes.count(),

        "total_pendientes": solicitudes.filter(
            estado="pendiente"
        ).count(),

        "total_aprobadas": solicitudes.filter(
            estado="aprobada"
        ).count(),

        "total_rechazadas": solicitudes.filter(
            estado="rechazada"
        ).count(),
    }

    return render(
        request,
        "solicitudes_campeonato.html",
        contexto
    )


@admin_required
@require_POST
def gestionar_solicitud(request, pk):
    """Aprueba o rechaza una solicitud de campeonato."""

    solicitud = get_object_or_404(
        SolicitudCampeonato.objects.select_related(
            "equipo",
            "campeonato"
        ),
        pk=pk
    )

    accion = request.POST.get("accion")

    if solicitud.estado != "pendiente":
        messages.warning(
            request,
            "Esta solicitud ya fue gestionada."
        )
        return redirect("solicitudes_campeonato")

    if accion == "aprobar":

        try:
            with transaction.atomic():

                InscripcionEquipo.objects.get_or_create(
                    equipo=solicitud.equipo,
                    campeonato=solicitud.campeonato
                )

                solicitud.estado = "aprobada"
                solicitud.save(update_fields=["estado"])

            messages.success(
                request,
                f"El equipo {solicitud.equipo.nombre} "
                f"fue inscrito en {solicitud.campeonato.nombre}."
            )

        except IntegrityError:
            messages.error(
                request,
                "No se pudo aprobar la solicitud."
            )

    elif accion == "rechazar":

        solicitud.estado = "rechazada"
        solicitud.save(update_fields=["estado"])

        messages.success(
            request,
            "La solicitud fue rechazada."
        )

    else:
        messages.error(
            request,
            "Acción no válida."
        )

    return redirect("solicitudes_campeonato")


# =========================================================
# CREAR, EDITAR Y ELIMINAR CAMPEONATOS
# =========================================================

@admin_required
def crear_campeonato(request):
    """Registra un campeonato nuevo."""

    contexto = {
        "campeonatos": Campeonato.objects.order_by("-fecha_inicio"),
    }

    return _guardar_modelo(
        request,
        Campeonato,
        ["nombre", "fecha_inicio", "fecha_termino", "estado"],
        "crear_campeonatos.html",
        contexto,
        "campeonatos",
    )


@admin_required
def editar_campeonato(request, pk):
    """Actualiza un campeonato existente."""

    campeonato = get_object_or_404(Campeonato, pk=pk)

    return _guardar_modelo(
        request,
        Campeonato,
        ["nombre", "fecha_inicio", "fecha_termino", "estado"],
        "editar_campeonatos.html",
        {"campeonato": campeonato},
        "campeonatos",
        instancia=campeonato,
    )


@admin_required
@require_POST
def eliminar_campeonato(request, pk):
    """Elimina un campeonato mediante POST."""

    campeonato = get_object_or_404(Campeonato, pk=pk)

    return _eliminar_modelo(
        request,
        campeonato,
        "campeonatos",
        "Campeonato",
    )


# =========================================================
# EQUIPOS
# =========================================================


@login_required(login_url="login")
def lista_equipos(request):
    """Muestra los equipos y sus campeonatos inscritos."""

    if request.user.is_staff:
        equipos = Equipo.objects.all()
    else:
        equipos = Equipo.objects.filter(
            usuario_delegado=request.user
        )

    equipos = list(
        equipos
        .select_related("id_campeonato", "usuario_delegado")
        .annotate(
            total_jugadores=Count("jugador", distinct=True)
        )
        .order_by("nombre")
    )

    # Obtener las inscripciones de los equipos.
    inscripciones = (
        InscripcionEquipo.objects
        .filter(equipo__in=equipos)
        .select_related("equipo", "campeonato")
        .order_by("campeonato__nombre")
    )

    # Agrupar los campeonatos por equipo.
    campeonatos_por_equipo = {}

    for inscripcion in inscripciones:
        equipo_id = inscripcion.equipo_id

        if equipo_id not in campeonatos_por_equipo:
            campeonatos_por_equipo[equipo_id] = []

        campeonatos_por_equipo[equipo_id].append(
            inscripcion.campeonato
        )

    # Entregar los campeonatos asociados a cada equipo.
    for equipo in equipos:

        campeonatos_equipo = campeonatos_por_equipo.get(
            equipo.pk,
            []
        )

        # Compatibilidad con equipos que tengan un campeonato
        # asociado directamente mediante id_campeonato.
        if equipo.id_campeonato_id:
            if not any(
                campeonato.pk == equipo.id_campeonato_id
                for campeonato in campeonatos_equipo
            ):
                campeonatos_equipo.append(equipo.id_campeonato)

        equipo.campeonatos_inscritos = campeonatos_equipo

    contexto = {
        "equipos": equipos,
        "campeonatos": Campeonato.objects.order_by("nombre"),
        "total_equipos": len(equipos),

        "total_jugadores": Jugador.objects.filter(
            id_equipo__in=equipos
        ).count(),

        "total_campeonatos": Campeonato.objects.count(),
    }

    return render(request, "equipos.html", contexto)



@login_required(login_url="login")
def crear_equipo(request):
    """Permite registrar equipos sin asociarlos inicialmente a un campeonato."""

    Formulario = modelform_factory(
        Equipo,
        fields=["nombre"]
    )

    formulario = Formulario(request.POST or None)

    if request.method == "POST" and formulario.is_valid():
        try:
            with transaction.atomic():
                equipo = formulario.save(commit=False)

                # Asignar automáticamente el delegado
                equipo.usuario_delegado = request.user

                nombre_delegado = request.user.get_full_name().strip()

                equipo.delegado = (
                    nombre_delegado
                    if nombre_delegado
                    else request.user.get_username()
                )

                # El equipo se crea sin campeonato asociado
                equipo.id_campeonato = None

                equipo.save()

            messages.success(
                request,
                f"El equipo {equipo.nombre} fue creado correctamente."
            )

            return redirect("equipos")

        except IntegrityError:
            messages.error(
                request,
                "No se pudo crear el equipo. Comprueba los datos."
            )

    contexto = {
        "form": formulario,
        "editando": False,
        "campeonatos": Campeonato.objects.order_by("nombre"),
    }

    return render(request, "crear_equipos.html", contexto)




@login_required(login_url="login")
def editar_equipo(request, pk):
    """Permite editar equipos al administrador o a su delegado."""

    equipo = get_object_or_404(Equipo, pk=pk)

    # ADMINISTRADOR: puede modificar todos los datos
    if request.user.is_staff:

        contexto = {
            "equipo": equipo,
            "campeonatos": Campeonato.objects.order_by("nombre"),
            "usuarios": User.objects.filter(
                is_staff=False,
                is_active=True
            ).order_by("username"),
        }

        return _guardar_modelo(
            request,
            Equipo,
            [
                "nombre",
                "delegado",
                "usuario_delegado",
                "id_campeonato",
            ],
            "editar_equipos.html",
            contexto,
            "equipos",
            instancia=equipo,
        )

    # DELEGADO: solamente puede editar su propio equipo
    if equipo.usuario_delegado != request.user:
        messages.error(
            request,
            "No tienes permiso para editar este equipo."
        )
        return redirect("equipos")

    Formulario = modelform_factory(
        Equipo,
        fields=["nombre"]
    )

    formulario = Formulario(
        request.POST or None,
        instance=equipo
    )

    if request.method == "POST" and formulario.is_valid():

        try:
            formulario.save()

            messages.success(
                request,
                "El equipo se actualizó correctamente."
            )

            return redirect("equipos")

        except IntegrityError:
            messages.error(
                request,
                "No se pudo actualizar el equipo."
            )

    contexto = {
        "form": formulario,
        "equipo": equipo,
        "editando": True,
        "campeonatos": Campeonato.objects.order_by("nombre"),
    }

    return render(
        request,
        "editar_equipos.html",
        contexto
    )



@login_required(login_url="login")
@require_POST
def eliminar_equipo(request, pk):
    """Permite eliminar equipos al administrador o a su delegado."""

    if request.user.is_staff:
        equipo = get_object_or_404(Equipo, pk=pk)
    else:
        equipo = get_object_or_404(
            Equipo,
            pk=pk,
            usuario_delegado=request.user
        )

    return _eliminar_modelo(
        request,
        equipo,
        "equipos",
        "Equipo",
    )


# =========================================================
# JUGADORES
# =========================================================

@login_required(login_url="login")
def lista_jugadores(request):
    """
    Muestra los jugadores con búsqueda y paginación.
    El administrador ve todos los jugadores.
    Cada delegado ve únicamente sus propios jugadores.
    """

    # ADMINISTRADOR
    if request.user.is_staff:
        jugadores = Jugador.objects.all()
        equipos = Equipo.objects.all()

    # DELEGADO
    else:
        equipos = Equipo.objects.filter(
            usuario_delegado=request.user
        )

        jugadores = Jugador.objects.filter(
            id_equipo__in=equipos
        )

    # TOTAL DE JUGADORES DEL USUARIO
    total_jugadores = jugadores.count()

    # BUSCADOR POR NOMBRE, APELLIDO O EQUIPO
    busqueda = request.GET.get("q", "").strip()

    if busqueda:
        jugadores = jugadores.filter(
            Q(nombre__icontains=busqueda)
            | Q(apellido__icontains=busqueda)
            | Q(id_equipo__nombre__icontains=busqueda)
        )

    # ORDENAMIENTO Y OPTIMIZACIÓN
    jugadores = (
        jugadores
        .select_related("id_equipo")
        .order_by("apellido", "nombre")
    )

    # PAGINACIÓN: 6 JUGADORES POR PÁGINA
    paginador = Paginator(jugadores, 6)

    numero_pagina = request.GET.get("page")

    page_obj = paginador.get_page(numero_pagina)

    contexto = {
        "jugadores": page_obj.object_list,
        "page_obj": page_obj,
        "equipos": equipos.order_by("nombre"),
        "total_jugadores": total_jugadores,
        "busqueda": busqueda,
    }

    return render(
        request,
        "jugadores.html",
        contexto
    )


@login_required(login_url="login")
def crear_jugador(request):
    """Permite registrar jugadores en los equipos propios del delegado."""

    if request.user.is_staff:
        equipos = Equipo.objects.all()
    else:
        equipos = Equipo.objects.filter(
            usuario_delegado=request.user
        )

    Formulario = modelform_factory(
        Jugador,
        fields=[
            "nombre",
            "apellido",
            "numero_camiseta",
            "id_equipo",
        ]
    )

    formulario = Formulario(request.POST or None)

    formulario.fields["id_equipo"].queryset = equipos.order_by("nombre")

    if request.method == "POST" and formulario.is_valid():

        try:
            with transaction.atomic():
                formulario.save()

            messages.success(
                request,
                "Jugador registrado correctamente."
            )

            return redirect("jugadores")

        except IntegrityError:
            messages.error(
                request,
                "No se pudo registrar el jugador. Comprueba los datos."
            )

    contexto = {
        "form": formulario,
        "equipos": equipos.order_by("nombre"),
        "editando": False,
    }

    return render(request, "crear_jugador.html", contexto)


@login_required(login_url="login")
def editar_jugador(request, pk):
    """Permite editar jugadores propios o cualquier jugador al administrador."""

    if request.user.is_staff:

        jugador = get_object_or_404(Jugador, pk=pk)
        equipos = Equipo.objects.all()

    else:

        jugador = get_object_or_404(
            Jugador,
            pk=pk,
            id_equipo__usuario_delegado=request.user
        )

        equipos = Equipo.objects.filter(
            usuario_delegado=request.user
        )

    Formulario = modelform_factory(
        Jugador,
        fields=[
            "nombre",
            "apellido",
            "numero_camiseta",
            "id_equipo",
        ]
    )

    formulario = Formulario(
        request.POST or None,
        instance=jugador
    )

    formulario.fields["id_equipo"].queryset = equipos.order_by("nombre")

    if request.method == "POST" and formulario.is_valid():

        try:
            with transaction.atomic():
                formulario.save()

            messages.success(
                request,
                "Jugador actualizado correctamente."
            )

            return redirect("jugadores")

        except IntegrityError:
            messages.error(
                request,
                "No se pudo actualizar el jugador."
            )

    contexto = {
        "form": formulario,
        "jugador": jugador,
        "equipos": equipos.order_by("nombre"),
        "editando": True,
    }

    return render(request, "editar_jugador.html", contexto)


@login_required(login_url="login")
@require_POST
def eliminar_jugador(request, pk):
    """Permite eliminar jugadores propios o cualquier jugador al administrador."""

    if request.user.is_staff:
        jugador = get_object_or_404(Jugador, pk=pk)
    else:
        jugador = get_object_or_404(
            Jugador,
            pk=pk,
            id_equipo__usuario_delegado=request.user
        )

    return _eliminar_modelo(
        request,
        jugador,
        "jugadores",
        "Jugador",
    )




# =========================================================
# PARTIDOS
# =========================================================

@login_required(login_url="login")
def lista_partidos(request):
    """
    El administrador puede consultar todos los partidos.
    El delegado solamente puede consultar los partidos
    en los que participa alguno de sus equipos.

    Carga también los jugadores, acontecimientos y sanciones
    para mostrar y gestionar los partidos en la plantilla.
    """

    # SANCIONES REGISTRADAS
    sanciones_partido = (
        Estadistica.objects
        .filter(
            Q(tarjetas_amarillas__gt=0)
            | Q(tarjetas_rojas__gt=0)
        )
        .select_related(
            "id_jugador",
            "id_jugador__id_equipo"
        )
    )

    # PARTIDOS, EQUIPOS, JUGADORES, EVENTOS Y SANCIONES
    partidos = (
        Partido.objects
        .select_related(
            "id_campeonato",
            "equipo_local",
            "equipo_visitante",
        )
        .prefetch_related(
            # Acontecimientos y jugador asociado
            "eventos__jugador",

            # Jugadores disponibles para registrar goles y tarjetas
            "equipo_local__jugador_set",
            "equipo_visitante__jugador_set",

            # Estadísticas de sanciones
            Prefetch(
                "estadistica_set",
                queryset=sanciones_partido,
                to_attr="sanciones_partido"
            )
        )
    )

    # FILTRAR PARTIDOS PARA DELEGADOS
    if not request.user.is_staff:
        partidos = partidos.filter(
            Q(equipo_local__usuario_delegado=request.user)
            | Q(equipo_visitante__usuario_delegado=request.user)
        )

    partidos = partidos.order_by(
        "-fecha",
        "-hora"
    ).distinct()

    # EQUIPOS DISPONIBLES SEGÚN EL USUARIO
    if request.user.is_staff:
        equipos = Equipo.objects.order_by("nombre")
    else:
        equipos = Equipo.objects.filter(
            usuario_delegado=request.user
        ).order_by("nombre")

    contexto = {
        "partidos": partidos,
        "total_partidos": partidos.count(),
        "campeonatos": Campeonato.objects.order_by("nombre"),
        "equipos": equipos,
    }

    return render(
        request,
        "partidos.html",
        contexto
    )



# =========================================================
# CREAR PARTIDO
# =========================================================


@admin_required
def crear_partido(request):
    """Permite al administrador registrar un partido."""

    contexto = {
        "campeonatos": Campeonato.objects.order_by("nombre"),

        "inscripciones_equipos": (
            InscripcionEquipo.objects
            .select_related("equipo", "campeonato")
            .order_by("campeonato__nombre", "equipo__nombre")
        ),
    }

    return _guardar_modelo(
        request,
        Partido,
        [
            "fecha",
            "hora",
            "id_campeonato",
            "equipo_local",
            "equipo_visitante",
        ],
        "crear_partido.html",
        contexto,
        "partidos",
    )



# =========================================================
# EDITAR PARTIDO
# =========================================================

@admin_required
def editar_partido(request, pk):
    """Permite al administrador editar un partido."""

    partido = get_object_or_404(
        Partido,
        pk=pk
    )

    contexto = {
        "partido": partido,
        "campeonatos": Campeonato.objects.order_by("nombre"),
        "equipos": Equipo.objects.order_by("nombre"),
    }

    return _guardar_modelo(
        request,
        Partido,
        [
            "fecha",
            "hora",
            "resultado_local",
            "resultado_visitante",
            "id_campeonato",
            "equipo_local",
            "equipo_visitante",
        ],
        "editar_partido.html",
        contexto,
        "partidos",
        instancia=partido,
    )


# =========================================================
# ELIMINAR PARTIDO
# =========================================================

@admin_required
@require_POST
def eliminar_partido(request, pk):
    """Permite al administrador eliminar un partido mediante POST."""

    partido = get_object_or_404(
        Partido,
        pk=pk
    )

    return _eliminar_modelo(
        request,
        partido,
        "partidos",
        "Partido",
    )


# =========================================================
# GESTIÓN DE PARTIDOS EN VIVO
# =========================================================



@admin_required
@require_POST
def gestionar_evento_partido(request, pk):
    """
    Gestiona goles, asistencias, tarjetas y períodos del encuentro:
    - Primer tiempo.
    - Segundo tiempo.
    - Primer tiempo del alargue.
    - Segundo tiempo del alargue.
    """

    accion = request.POST.get("accion", "").strip()

    mensaje_notificacion = None
    minuto = None
    jugador_nombre = None
    asistente_nombre = None

    try:
        with transaction.atomic():

            partido = get_object_or_404(
                Partido.objects.select_for_update(),
                pk=pk
            )

            # =========================================
            # INICIAR PARTIDO
            # =========================================

            if accion == "iniciar":

                if partido.estado != "programado":
                    messages.warning(
                        request,
                        "Este partido no se encuentra programado."
                    )
                    return redirect("partidos")

                partido.estado = "en_juego"
                partido.periodo = "primer_tiempo"

                partido.save(
                    update_fields=["estado", "periodo"]
                )

                mensaje_notificacion = "¡El partido ha comenzado!"

                EventoPartido.objects.create(
                    partido=partido,
                    tipo="iniciar",
                    descripcion=mensaje_notificacion
                )

                messages.success(request, mensaje_notificacion)

            # =========================================
            # REGISTRAR GOLES Y ASISTENCIAS
            # =========================================

            elif accion in ("gol_local", "gol_visitante"):

                if partido.estado != "en_juego":
                    messages.error(
                        request,
                        "Solo puedes registrar goles durante el partido."
                    )
                    return redirect("partidos")

                jugador_id = (
                    request.POST.get("id_jugador")
                    or request.POST.get("jugador_id")
                    or ""
                ).strip()

                if not jugador_id:
                    messages.error(
                        request,
                        "Debes seleccionar al goleador."
                    )
                    return redirect("partidos")

                equipo_id = (
                    partido.equipo_local_id
                    if accion == "gol_local"
                    else partido.equipo_visitante_id
                )

                jugador = Jugador.objects.filter(
                    pk=jugador_id,
                    id_equipo_id=equipo_id
                ).first()

                if not jugador:
                    messages.error(
                        request,
                        "El jugador no pertenece al equipo correspondiente."
                    )
                    return redirect("partidos")

                # VALIDAR ASISTENTE

                asistente_id = request.POST.get(
                    "id_asistente", ""
                ).strip()

                asistente = None

                if asistente_id:

                    asistente = Jugador.objects.filter(
                        pk=asistente_id,
                        id_equipo_id=equipo_id
                    ).first()

                    if not asistente:
                        messages.error(
                            request,
                            "El asistente debe pertenecer al mismo equipo."
                        )
                        return redirect("partidos")

                    if asistente.pk == jugador.pk:
                        messages.error(
                            request,
                            "El goleador no puede ser su propio asistente."
                        )
                        return redirect("partidos")

                    asistente_nombre = str(asistente)

                # VALIDAR MINUTO

                minuto_texto = request.POST.get(
                    "minuto", ""
                ).strip()

                if minuto_texto:
                    try:
                        minuto = int(minuto_texto)
                    except (ValueError, TypeError):
                        messages.error(
                            request,
                            "El minuto debe ser un número válido."
                        )
                        return redirect("partidos")

                    if not 0 <= minuto <= 150:
                        messages.error(
                            request,
                            "El minuto debe estar entre 0 y 150."
                        )
                        return redirect("partidos")

                # ACTUALIZAR MARCADOR

                if accion == "gol_local":
                    partido.resultado_local += 1
                    equipo_nombre = partido.equipo_local.nombre
                else:
                    partido.resultado_visitante += 1
                    equipo_nombre = partido.equipo_visitante.nombre

                partido.save(
                    update_fields=[
                        "resultado_local",
                        "resultado_visitante"
                    ]
                )

                # SUMAR GOL AL GOLEADOR

                estadistica, creada = Estadistica.objects.get_or_create(
                    id_partido=partido,
                    id_jugador=jugador
                )

                estadistica.goles += 1

                estadistica.save(
                    update_fields=["goles"]
                )

                # SUMAR ASISTENCIA AL JUGADOR

                if asistente:

                    estadistica_asistente, creada = (
                        Estadistica.objects.get_or_create(
                            id_partido=partido,
                            id_jugador=asistente
                        )
                    )

                    estadistica_asistente.asistencias += 1

                    estadistica_asistente.save(
                        update_fields=["asistencias"]
                    )

                # REGISTRAR ACONTECIMIENTO

                jugador_nombre = str(jugador)

                descripcion = (
                    f"¡GOOOL de {equipo_nombre}! "
                    f"Anotado por {jugador_nombre}"
                )

                if asistente:
                    descripcion += (
                        f". Asistencia de {asistente_nombre}"
                    )

                if minuto is not None:
                    descripcion += f" al minuto {minuto}'"

                EventoPartido.objects.create(
                    partido=partido,
                    jugador=jugador,
                    tipo=accion,
                    minuto=minuto,
                    descripcion=descripcion
                )

                mensaje_notificacion = (
                    f"{descripcion}. Marcador: "
                    f"{partido.resultado_local} - "
                    f"{partido.resultado_visitante}"
                )

                messages.success(request, mensaje_notificacion)

            # =========================================
            # REGISTRAR TARJETAS
            # =========================================

            elif accion in (
                "tarjeta_amarilla",
                "tarjeta_roja"
            ):

                if partido.estado != "en_juego":
                    messages.error(
                        request,
                        "Solo puedes registrar tarjetas durante el partido."
                    )
                    return redirect("partidos")

                jugador_id = (
                    request.POST.get("id_jugador")
                    or request.POST.get("jugador_id")
                    or ""
                ).strip()

                if not jugador_id:
                    messages.error(
                        request,
                        "Debes seleccionar al jugador sancionado."
                    )
                    return redirect("partidos")

                jugador = Jugador.objects.filter(
                    pk=jugador_id,
                    id_equipo_id__in=[
                        partido.equipo_local_id,
                        partido.equipo_visitante_id
                    ]
                ).select_related("id_equipo").first()

                if not jugador:
                    messages.error(
                        request,
                        "El jugador no pertenece a los equipos del encuentro."
                    )
                    return redirect("partidos")

                minuto_texto = request.POST.get(
                    "minuto", ""
                ).strip()

                if minuto_texto:
                    try:
                        minuto = int(minuto_texto)
                    except (ValueError, TypeError):
                        messages.error(
                            request,
                            "El minuto debe ser un número válido."
                        )
                        return redirect("partidos")

                    if not 0 <= minuto <= 150:
                        messages.error(
                            request,
                            "El minuto debe estar entre 0 y 150."
                        )
                        return redirect("partidos")

                estadistica, creada = Estadistica.objects.get_or_create(
                    id_partido=partido,
                    id_jugador=jugador
                )

                if accion == "tarjeta_amarilla":
                    estadistica.tarjetas_amarillas += 1
                    tipo_tarjeta = "Tarjeta amarilla"
                else:
                    estadistica.tarjetas_rojas += 1
                    tipo_tarjeta = "Tarjeta roja"

                estadistica.save(
                    update_fields=[
                        "tarjetas_amarillas",
                        "tarjetas_rojas"
                    ]
                )

                jugador_nombre = str(jugador)

                descripcion = (
                    f"{tipo_tarjeta} para {jugador_nombre} "
                    f"({jugador.id_equipo.nombre})"
                )

                if minuto is not None:
                    descripcion += f" al minuto {minuto}'"

                EventoPartido.objects.create(
                    partido=partido,
                    jugador=jugador,
                    tipo=accion,
                    minuto=minuto,
                    descripcion=descripcion
                )

                mensaje_notificacion = descripcion

                messages.success(request, mensaje_notificacion)

            # =========================================
            # FINALIZAR PRIMER TIEMPO REGLAMENTARIO
            # =========================================

            elif accion == "fin_primer_tiempo":

                if (
                    partido.estado != "en_juego"
                    or partido.periodo != "primer_tiempo"
                ):
                    messages.error(
                        request,
                        "No corresponde finalizar el primer tiempo."
                    )
                    return redirect("partidos")

                partido.estado = "descanso"

                partido.save(update_fields=["estado"])

                mensaje_notificacion = (
                    "Final del primer tiempo. Marcador: "
                    f"{partido.resultado_local} - "
                    f"{partido.resultado_visitante}"
                )

                EventoPartido.objects.create(
                    partido=partido,
                    tipo="fin_primer_tiempo",
                    descripcion=mensaje_notificacion
                )

                messages.success(request, mensaje_notificacion)

            # =========================================
            # INICIAR SEGUNDO TIEMPO REGLAMENTARIO
            # =========================================

            elif accion == "iniciar_segundo_tiempo":

                if (
                    partido.estado != "descanso"
                    or partido.periodo != "primer_tiempo"
                ):
                    messages.error(
                        request,
                        "No corresponde iniciar el segundo tiempo."
                    )
                    return redirect("partidos")

                partido.estado = "en_juego"
                partido.periodo = "segundo_tiempo"

                partido.save(
                    update_fields=["estado", "periodo"]
                )

                mensaje_notificacion = "¡Comenzó el segundo tiempo!"

                EventoPartido.objects.create(
                    partido=partido,
                    tipo="iniciar_segundo_tiempo",
                    descripcion=mensaje_notificacion
                )

                messages.success(request, mensaje_notificacion)

            # =========================================
            # INICIAR PRIMER TIEMPO DEL ALARGUE
            # =========================================

            elif accion == "iniciar_alargue_primer_tiempo":

                if (
                    partido.estado != "en_juego"
                    or partido.periodo != "segundo_tiempo"
                ):
                    messages.error(
                        request,
                        "No corresponde iniciar el alargue."
                    )
                    return redirect("partidos")

                if (
                    partido.resultado_local
                    != partido.resultado_visitante
                ):
                    messages.error(
                        request,
                        "El alargue solamente puede iniciarse "
                        "si el encuentro termina empatado."
                    )
                    return redirect("partidos")

                partido.periodo = "alargue_primer_tiempo"

                partido.save(update_fields=["periodo"])

                mensaje_notificacion = (
                    "¡Comenzó el primer tiempo del alargue!"
                )

                EventoPartido.objects.create(
                    partido=partido,
                    tipo="iniciar_alargue_primer_tiempo",
                    descripcion=mensaje_notificacion
                )

                messages.success(request, mensaje_notificacion)

            # =========================================
            # FINALIZAR PRIMER TIEMPO DEL ALARGUE
            # =========================================

            elif accion == "fin_alargue_primer_tiempo":

                if (
                    partido.estado != "en_juego"
                    or partido.periodo != "alargue_primer_tiempo"
                ):
                    messages.error(
                        request,
                        "No corresponde finalizar el primer tiempo del alargue."
                    )
                    return redirect("partidos")

                partido.estado = "descanso"

                partido.save(update_fields=["estado"])

                mensaje_notificacion = (
                    "Finalizó el primer tiempo del alargue."
                )

                EventoPartido.objects.create(
                    partido=partido,
                    tipo="fin_alargue_primer_tiempo",
                    descripcion=mensaje_notificacion
                )

                messages.success(request, mensaje_notificacion)

            # =========================================
            # INICIAR SEGUNDO TIEMPO DEL ALARGUE
            # =========================================

            elif accion == "iniciar_alargue_segundo_tiempo":

                if (
                    partido.estado != "descanso"
                    or partido.periodo != "alargue_primer_tiempo"
                ):
                    messages.error(
                        request,
                        "No corresponde iniciar el segundo tiempo del alargue."
                    )
                    return redirect("partidos")

                partido.estado = "en_juego"
                partido.periodo = "alargue_segundo_tiempo"

                partido.save(
                    update_fields=["estado", "periodo"]
                )

                mensaje_notificacion = (
                    "¡Comenzó el segundo tiempo del alargue!"
                )

                EventoPartido.objects.create(
                    partido=partido,
                    tipo="iniciar_alargue_segundo_tiempo",
                    descripcion=mensaje_notificacion
                )

                messages.success(request, mensaje_notificacion)

            # =========================================
            # FINALIZAR PARTIDO
            # =========================================

            elif accion == "partido_finalizado":

                puede_finalizar = (
                    (
                        partido.estado == "en_juego"
                        and partido.periodo == "segundo_tiempo"
                    )
                    or (
                        partido.estado == "en_juego"
                        and partido.periodo == "alargue_segundo_tiempo"
                    )
                )

                if not puede_finalizar:
                    messages.error(
                        request,
                        "No puedes finalizar el partido en este período."
                    )
                    return redirect("partidos")

                partido.estado = "finalizado"

                partido.save(update_fields=["estado"])

                mensaje_notificacion = (
                    "¡Partido finalizado! Resultado definitivo: "
                    f"{partido.resultado_local} - "
                    f"{partido.resultado_visitante}"
                )

                EventoPartido.objects.create(
                    partido=partido,
                    tipo="partido_finalizado",
                    descripcion=mensaje_notificacion
                )

                messages.success(request, mensaje_notificacion)

            # =========================================
            # ACCIÓN NO RECONOCIDA
            # =========================================

            else:
                messages.error(
                    request,
                    "La acción solicitada no es válida."
                )
                return redirect("partidos")

            # =========================================
            # NOTIFICAR POR WEBSOCKET
            # =========================================

            if mensaje_notificacion:

                datos = {
                    "tipo": accion,
                    "mensaje": mensaje_notificacion,
                    "partido_id": partido.pk,
                    "equipo_local": partido.equipo_local.nombre,
                    "equipo_visitante": partido.equipo_visitante.nombre,
                    "resultado_local": partido.resultado_local,
                    "resultado_visitante": partido.resultado_visitante,
                    "estado": partido.estado,
                    "periodo": partido.periodo,
                    "minuto": minuto,
                    "jugador": jugador_nombre,
                    "asistente": asistente_nombre,
                }

                def enviar_actualizacion(
                    datos=datos,
                    partido_id=partido.pk
                ):
                    channel_layer = get_channel_layer()

                    if channel_layer is not None:
                        async_to_sync(channel_layer.group_send)(
                            f"partido_{partido_id}",
                            {
                                "type": "partido_actualizado",
                                "data": datos
                            }
                        )

                transaction.on_commit(enviar_actualizacion)

    except IntegrityError:
        messages.error(
            request,
            "No se pudo registrar el acontecimiento. "
            "Inténtalo nuevamente."
        )

    return redirect("partidos")



# =========================================================
# ESTADÍSTICAS
# =========================================================

@login_required(login_url="login")
def lista_estadisticas(request):
    """Muestra las estadísticas y calcula sus totales."""

    estadisticas = (
        Estadistica.objects
        .select_related(
            "id_jugador",
            "id_partido",
            "id_jugador__id_equipo",
            "id_partido__id_campeonato",
            "id_partido__equipo_local",
            "id_partido__equipo_visitante",
        )
        .order_by(
            "-goles",
            "-asistencias",
            "id_jugador__apellido",
            "id_jugador__nombre",
        )
    )

    totales = estadisticas.aggregate(
        total_goles=Sum("goles"),
        total_asistencias=Sum("asistencias"),
    )

    contexto = {
        "estadisticas": estadisticas,
        "jugadores": Jugador.objects.order_by("apellido", "nombre"),

        "partidos": (
            Partido.objects
            .select_related(
                "equipo_local",
                "equipo_visitante",
                "id_campeonato",
            )
            .order_by("-fecha", "-hora")
        ),

        "total_registros": estadisticas.count(),
        "total_goles": totales["total_goles"] or 0,
        "total_asistencias": totales["total_asistencias"] or 0,
    }

    return render(request, "estadisticas.html", contexto)


@admin_required
def crear_estadistica(request):
    """Registra las estadísticas de un jugador en un partido."""

    contexto = {
        "campeonatos": Campeonato.objects.order_by("nombre"),
        "jugadores": Jugador.objects.order_by("apellido", "nombre"),

        "partidos": (
            Partido.objects
            .select_related(
                "equipo_local",
                "equipo_visitante",
                "id_campeonato",
            )
            .order_by("-fecha", "-hora")
        ),
    }

    return _guardar_modelo(
        request,
        Estadistica,
        [
            "id_partido",
            "id_jugador",
            "goles",
            "asistencias",
            "tarjetas_amarillas",
            "tarjetas_rojas",
        ],
        "crear_estadistica.html",
        contexto,
        "estadisticas",
    )


@admin_required
def editar_estadistica(request, pk):
    """Actualiza las estadísticas de un jugador."""

    estadistica = get_object_or_404(Estadistica, pk=pk)

    contexto = {
        "campeonatos": Campeonato.objects.order_by("nombre"),
        "jugadores": Jugador.objects.order_by("apellido", "nombre"),

        "partidos": (
            Partido.objects
            .select_related(
                "equipo_local",
                "equipo_visitante",
                "id_campeonato",
            )
            .order_by("-fecha", "-hora")
        ),

        "estadistica": estadistica,
    }

    return _guardar_modelo(
        request,
        Estadistica,
        [
            "id_partido",
            "id_jugador",
            "goles",
            "asistencias",
            "tarjetas_amarillas",
            "tarjetas_rojas",
        ],
        "editar_estadistica.html",
        contexto,
        "estadisticas",
        instancia=estadistica,
    )


@admin_required
@require_POST
def eliminar_estadistica(request, pk):
    """Elimina una estadística mediante POST."""

    estadistica = get_object_or_404(Estadistica, pk=pk)

    return _eliminar_modelo(
        request,
        estadistica,
        "estadisticas",
        "Estadística",
    )


# =========================================================
# SANCIONES: CONSULTAR
# =========================================================

@login_required(login_url="login")
def sanciones(request):
    """Muestra las sanciones registradas."""

    registros = (
        Estadistica.objects
        .select_related(
            "id_jugador",
            "id_jugador__id_equipo",
            "id_partido",
            "id_partido__equipo_local",
            "id_partido__equipo_visitante",
        )
        .filter(
            Q(tarjetas_amarillas__gt=0)
            | Q(tarjetas_rojas__gt=0)
        )
        .order_by(
            "-id_partido__fecha",
            "-id_partido__hora"
        )
    )

    contexto = {
        "partidos": (
            Partido.objects
            .select_related("equipo_local", "equipo_visitante")
            .order_by("-fecha", "-hora")
        ),

        "jugadores": (
            Jugador.objects
            .select_related("id_equipo")
            .order_by(
                "id_equipo__nombre",
                "apellido",
                "nombre"
            )
        ),

        "sanciones": registros,
        "equipos": Equipo.objects.order_by("nombre"),
    }

    return render(request, "sanciones.html", contexto)


# =========================================================
# SANCIONES: REGISTRAR
# =========================================================

@admin_required
@require_POST
def registrar_sancion(request):
    """Registra o actualiza las tarjetas de un jugador."""

    jugador_id = request.POST.get("id_jugador", "").strip()
    partido_id = request.POST.get("id_partido", "").strip()

    if not jugador_id or not partido_id:
        messages.error(
            request,
            "Debes seleccionar un partido y un jugador."
        )
        return redirect("sanciones")

    try:
        amarillas = int(
            request.POST.get("tarjetas_amarillas", "0")
        )

        rojas = int(
            request.POST.get("tarjetas_rojas", "0")
        )

        jugador_id = int(jugador_id)
        partido_id = int(partido_id)

        if (
            amarillas < 0
            or rojas < 0
            or jugador_id <= 0
            or partido_id <= 0
        ):
            raise ValueError

        if amarillas >= 2:
            rojas = max(rojas, 1)

    except (TypeError, ValueError):
        messages.error(
            request,
            "Ingresa cantidades enteras no negativas y "
            "selecciona un jugador y partido válidos."
        )
        return redirect("sanciones")

    jugador = get_object_or_404(Jugador, pk=jugador_id)
    partido = get_object_or_404(Partido, pk=partido_id)

    equipos_partido = {
        partido.equipo_local_id,
        partido.equipo_visitante_id,
    }

    if jugador.id_equipo_id not in equipos_partido:
        messages.error(
            request,
            "El jugador debe pertenecer a uno de los equipos del partido."
        )
        return redirect("sanciones")

    try:
        with transaction.atomic():

            registro, creado = Estadistica.objects.get_or_create(
                id_jugador=jugador,
                id_partido=partido,

                defaults={
                    "goles": 0,
                    "asistencias": 0,
                    "tarjetas_amarillas": amarillas,
                    "tarjetas_rojas": rojas,
                },
            )

            if not creado:
                registro.tarjetas_amarillas = amarillas
                registro.tarjetas_rojas = rojas

                registro.save(
                    update_fields=[
                        "tarjetas_amarillas",
                        "tarjetas_rojas",
                    ]
                )

    except IntegrityError:
        messages.error(
            request,
            "No fue posible guardar la sanción. Revisa la base de datos."
        )
        return redirect("sanciones")

    if creado:
        messages.success(
            request,
            "Sanción registrada correctamente."
        )
    else:
        messages.success(
            request,
            "Sanción actualizada correctamente."
        )

    return redirect("sanciones")


# =========================================================
# SANCIONES: EDITAR
# =========================================================

@admin_required
def editar_sancion(request, pk):
    """Actualiza las tarjetas de una estadística existente."""

    sancion = get_object_or_404(Estadistica, pk=pk)

    if request.method == "POST":

        try:
            amarillas = int(
                request.POST.get("tarjetas_amarillas", "0")
            )

            rojas = int(
                request.POST.get("tarjetas_rojas", "0")
            )

            if amarillas < 0 or rojas < 0:
                raise ValueError

            if amarillas >= 2:
                rojas = max(rojas, 1)

            sancion.tarjetas_amarillas = amarillas
            sancion.tarjetas_rojas = rojas

            sancion.save(
                update_fields=[
                    "tarjetas_amarillas",
                    "tarjetas_rojas",
                ]
            )

            messages.success(
                request,
                "La sanción se actualizó correctamente."
            )

            return redirect("sanciones")

        except (TypeError, ValueError):
            messages.error(
                request,
                "Ingresa cantidades enteras no negativas."
            )

    return render(
        request,
        "editar_sancion.html",
        {"sancion": sancion},
    )


# =========================================================
# SANCIONES: ELIMINAR
# =========================================================

@admin_required
@require_POST
def eliminar_sancion(request, pk):
    """Elimina las tarjetas sin borrar goles ni asistencias."""

    sancion = get_object_or_404(Estadistica, pk=pk)

    if not sancion.goles and not sancion.asistencias:
        sancion.delete()

    else:
        sancion.tarjetas_amarillas = 0
        sancion.tarjetas_rojas = 0

        sancion.save(
            update_fields=[
                "tarjetas_amarillas",
                "tarjetas_rojas",
            ]
        )

    messages.success(
        request,
        "La sanción se eliminó correctamente."
    )

    return redirect("sanciones")


# =========================================================
# PANEL ADMINISTRATIVO PERSONALIZADO
# =========================================================

@admin_required
@never_cache
def panel_admin(request):
    """Panel administrativo con resumen y próximos partidos."""

    total_campeonatos = Campeonato.objects.count()
    total_equipos = Equipo.objects.count()
    total_jugadores = Jugador.objects.count()
    total_partidos = Partido.objects.count()

    resumen = Estadistica.objects.aggregate(
        total_goles=Sum("goles"),
        total_asistencias=Sum("asistencias"),
        total_amarillas=Sum("tarjetas_amarillas"),
        total_rojas=Sum("tarjetas_rojas"),
    )

    total_goles = resumen["total_goles"] or 0
    total_asistencias = resumen["total_asistencias"] or 0
    total_amarillas = resumen["total_amarillas"] or 0
    total_rojas = resumen["total_rojas"] or 0

    ultimos_partidos = (
        Partido.objects
        .select_related(
            "equipo_local",
            "equipo_visitante",
            "id_campeonato",
        )
        .order_by("-fecha", "-hora")[:6]
    )

    hoy = timezone.localdate()

    proximos_partidos = (
        Partido.objects
        .filter(fecha__gte=hoy)
        .select_related(
            "equipo_local",
            "equipo_visitante",
            "id_campeonato",
        )
        .order_by("fecha", "hora")[:5]
    )

    goleadores = (
        Estadistica.objects
        .values(
            "id_jugador",
            "id_jugador__nombre",
            "id_jugador__apellido",
        )
        .annotate(total_goles=Sum("goles"))
        .filter(total_goles__gt=0)
        .order_by("-total_goles", "id_jugador__apellido")[:5]
    )

    equipos_destacados = (
        Equipo.objects
        .annotate(total_jugadores=Count("jugador"))
        .order_by("-total_jugadores", "nombre")[:5]
    )

    campeonatos_recientes = (
        Campeonato.objects
        .order_by("-fecha_inicio")[:5]
    )

    alertas = []

    if total_campeonatos == 0:
        alertas.append({
            "tipo": "advertencia",
            "titulo": "No hay campeonatos registrados",
            "mensaje": (
                "Crea un campeonato para comenzar a organizar "
                "la competición."
            ),
            "url": "crear_campeonato",
            "accion": "Crear campeonato",
        })

    if total_equipos == 0:
        alertas.append({
            "tipo": "advertencia",
            "titulo": "No hay equipos registrados",
            "mensaje": (
                "Registra los equipos que participarán "
                "en los campeonatos."
            ),
            "url": "crear_equipo",
            "accion": "Registrar equipo",
        })

    if total_jugadores == 0 and total_equipos > 0:
        alertas.append({
            "tipo": "informacion",
            "titulo": "Faltan jugadores",
            "mensaje": (
                "Todavía no hay jugadores registrados "
                "en el sistema."
            ),
            "url": "jugadores",
            "accion": "Ver jugadores",
        })

    if total_partidos == 0 and total_campeonatos > 0:
        alertas.append({
            "tipo": "informacion",
            "titulo": "No hay partidos programados",
            "mensaje": (
                "Puedes comenzar creando los partidos "
                "del campeonato."
            ),
            "url": "crear_partido",
            "accion": "Crear partido",
        })

    contexto = {
        "total_campeonatos": total_campeonatos,
        "total_equipos": total_equipos,
        "total_jugadores": total_jugadores,
        "total_partidos": total_partidos,

        "total_goles": total_goles,
        "total_asistencias": total_asistencias,
        "total_amarillas": total_amarillas,
        "total_rojas": total_rojas,

        "ultimos_partidos": ultimos_partidos,
        "proximos_partidos": proximos_partidos,
        "goleadores": goleadores,
        "equipos_destacados": equipos_destacados,
        "campeonatos_recientes": campeonatos_recientes,

        "alertas": alertas,
        "total_alertas": len(alertas),
    }

    return render(request, "panel_admin.html", contexto)


# =========================================================
# AUTENTICACIÓN: INICIAR SESIÓN
# =========================================================

@never_cache
def iniciar_sesion(request):
    """Inicia sesión y redirige según el tipo de usuario."""

    if request.user.is_authenticated:

        if request.user.is_staff:
            return redirect("indexadmin")

        return redirect("index")

    datos = (
        request.POST.copy()
        if request.method == "POST"
        else None
    )

    if request.method == "POST":

        identificador = request.POST.get(
            "username",
            ""
        ).strip()

        if "@" in identificador:

            usuario = User.objects.filter(
                email__iexact=identificador
            ).first()

            if usuario:
                datos["username"] = usuario.get_username()

    formulario = AuthenticationForm(
        request,
        data=datos
    )

    if request.method == "POST" and formulario.is_valid():

        usuario = formulario.get_user()

        login(request, usuario)

        messages.success(
            request,
            f"Bienvenido, {usuario.username}."
        )

        if usuario.is_staff:
            return redirect("indexadmin")

        return redirect("index")

    return render(
        request,
        "iniciarsesion.html",
        {"form": formulario},
    )


# =========================================================
# AUTENTICACIÓN: REGISTRARSE
# =========================================================

@never_cache
def registrarse(request):
    """Crea una cuenta nueva de delegado."""

    if request.user.is_authenticated:

        if request.user.is_staff:
            return redirect("indexadmin")

        return redirect("index")

    formulario = UserCreationForm(
        request.POST or None
    )

    if request.method == "POST" and formulario.is_valid():

        correo = request.POST.get(
            "email",
            ""
        ).strip()

        if not correo:
            messages.error(
                request,
                "Debes ingresar un correo electrónico."
            )

            return render(
                request,
                "registrarse.html",
                {"form": formulario},
            )

        if User.objects.filter(
            email__iexact=correo
        ).exists():

            messages.error(
                request,
                "Este correo electrónico ya está registrado."
            )

            return render(
                request,
                "registrarse.html",
                {"form": formulario},
            )

        try:
            with transaction.atomic():

                usuario = formulario.save(commit=False)

                usuario.email = correo
                usuario.is_staff = False
                usuario.is_superuser = False
                usuario.is_active = True

                usuario.save()

            login(request, usuario)

            messages.success(
                request,
                "Tu cuenta de delegado fue creada correctamente."
            )

            return redirect("index")

        except IntegrityError:
            messages.error(
                request,
                "No se pudo crear la cuenta. "
                "Comprueba los datos e inténtalo nuevamente."
            )

    return render(
        request,
        "registrarse.html",
        {"form": formulario},
    )


# =========================================================
# AUTENTICACIÓN: CERRAR SESIÓN
# =========================================================

@require_POST
def cerrar_sesion(request):
    """Cierra la sesión del usuario actual."""

    logout(request)

    messages.success(
        request,
        "Has cerrado sesión correctamente."
    )

    return redirect("login")

# =========================================================
# FUNCIONES AUXILIARES DEL PANEL DEL DELEGADO
# =========================================================

def _obtener_tabla_posiciones(campeonato, equipos_usuario_ids):
    """
    Calcula la tabla general de un campeonato.
    Incluye todos los equipos inscritos y destaca
    los equipos pertenecientes al delegado.
    """

    inscripciones = (
        InscripcionEquipo.objects
        .filter(campeonato=campeonato)
        .select_related("equipo")
    )

    tabla = {}

    for inscripcion in inscripciones:
        equipo = inscripcion.equipo
        equipo_id = equipo.id_equipo

        tabla[equipo_id] = {
            "equipo": equipo,
            "pj": 0,
            "pg": 0,
            "pe": 0,
            "pp": 0,
            "gf": 0,
            "gc": 0,
            "dg": 0,
            "pts": 0,
            "es_mio": equipo_id in equipos_usuario_ids,
        }

    partidos = (
        Partido.objects
        .filter(
            id_campeonato=campeonato,
            resultado_local__isnull=False,
            resultado_visitante__isnull=False,
        )
        .select_related(
            "equipo_local",
            "equipo_visitante",
        )
    )

    for partido in partidos:

        local_id = partido.equipo_local_id
        visitante_id = partido.equipo_visitante_id

        if local_id not in tabla or visitante_id not in tabla:
            continue

        goles_local = partido.resultado_local
        goles_visitante = partido.resultado_visitante

        local = tabla[local_id]
        visitante = tabla[visitante_id]

        local["pj"] += 1
        visitante["pj"] += 1

        local["gf"] += goles_local
        local["gc"] += goles_visitante

        visitante["gf"] += goles_visitante
        visitante["gc"] += goles_local

        if goles_local > goles_visitante:

            local["pg"] += 1
            local["pts"] += 3
            visitante["pp"] += 1

        elif goles_local < goles_visitante:

            visitante["pg"] += 1
            visitante["pts"] += 3
            local["pp"] += 1

        else:

            local["pe"] += 1
            visitante["pe"] += 1

            local["pts"] += 1
            visitante["pts"] += 1

    posiciones = list(tabla.values())

    for fila in posiciones:
        fila["dg"] = fila["gf"] - fila["gc"]

    posiciones.sort(
        key=lambda fila: (
            -fila["pts"],
            -fila["dg"],
            -fila["gf"],
            fila["equipo"].nombre.lower(),
        )
    )

    for numero, fila in enumerate(posiciones, start=1):
        fila["posicion"] = numero

    return posiciones


# =========================================================
# INICIO DEL DELEGADO
# =========================================================

@never_cache
@login_required(login_url="login")
def index(request):
    """
    Panel de consulta exclusivo del delegado.
    """

    if request.user.is_staff:
        return redirect("indexadmin")

    hoy = timezone.localdate()
    ahora = timezone.localtime().time()

    # -----------------------------------------------------
    # EQUIPOS DEL DELEGADO
    # -----------------------------------------------------

    equipos_usuario = (
        Equipo.objects
        .filter(usuario_delegado=request.user)
        .select_related("usuario_delegado")
        .order_by("nombre")
    )

    equipos_usuario_ids = set(
        equipos_usuario.values_list("id_equipo", flat=True)
    )

    total_equipos = len(equipos_usuario_ids)

    # -----------------------------------------------------
    # JUGADORES DEL DELEGADO
    # -----------------------------------------------------

    jugadores_usuario = (
        Jugador.objects
        .filter(id_equipo__in=equipos_usuario_ids)
        .select_related("id_equipo")
        .order_by("apellido", "nombre")
    )

    total_jugadores = jugadores_usuario.count()

    # -----------------------------------------------------
    # CAMPEONATOS DE SUS EQUIPOS INSCRITOS
    # -----------------------------------------------------

    campeonatos_usuario = (
        Campeonato.objects
        .filter(
            inscripciones__equipo__usuario_delegado=request.user
        )
        .distinct()
        .order_by("-fecha_inicio")
    )

    total_campeonatos = campeonatos_usuario.count()

    # -----------------------------------------------------
    # PARTIDOS YA INICIADOS O DISPUTADOS
    # -----------------------------------------------------

    partidos_iniciados = (
        Q(fecha__lt=hoy)
        | Q(fecha=hoy, hora__lte=ahora)
        | Q(fecha=hoy, hora__isnull=True)
    )

    partidos = (
        Partido.objects
        .filter(
            Q(equipo_local__usuario_delegado=request.user)
            | Q(equipo_visitante__usuario_delegado=request.user)
        )
        .filter(partidos_iniciados)
        .select_related(
            "id_campeonato",
            "equipo_local",
            "equipo_visitante",
        )
        .order_by("-fecha", "-hora")
        .distinct()
    )

    total_partidos = partidos.count()

    # -----------------------------------------------------
    # ESTADÍSTICAS DE SUS JUGADORES
    # -----------------------------------------------------

    estadisticas = (
        Estadistica.objects
        .filter(id_jugador__in=jugadores_usuario)
        .filter(
            Q(id_partido__fecha__lt=hoy)
            | Q(
                id_partido__fecha=hoy,
                id_partido__hora__lte=ahora,
            )
            | Q(
                id_partido__fecha=hoy,
                id_partido__hora__isnull=True,
            )
        )
        .select_related(
            "id_jugador",
            "id_jugador__id_equipo",
            "id_partido",
            "id_partido__id_campeonato",
        )
    )

    resumen_estadisticas = estadisticas.aggregate(
        total_goles=Sum("goles"),
        total_asistencias=Sum("asistencias"),
    )

    total_goles = resumen_estadisticas["total_goles"] or 0
    total_asistencias = resumen_estadisticas["total_asistencias"] or 0

    total_jugadores_estadisticas = (
        estadisticas
        .values("id_jugador")
        .distinct()
        .count()
    )

    # -----------------------------------------------------
    # GOLEADORES
    # -----------------------------------------------------

    goleadores = (
        estadisticas
        .values(
            "id_jugador",
            "id_jugador__nombre",
            "id_jugador__apellido",
            "id_jugador__id_equipo__nombre",
        )
        .annotate(goles=Sum("goles"))
        .filter(goles__gt=0)
        .order_by("-goles", "id_jugador__apellido")[:10]
    )

    # -----------------------------------------------------
    # ASISTIDORES
    # -----------------------------------------------------

    asistidores = (
        estadisticas
        .values(
            "id_jugador",
            "id_jugador__nombre",
            "id_jugador__apellido",
            "id_jugador__id_equipo__nombre",
        )
        .annotate(asistencias=Sum("asistencias"))
        .filter(asistencias__gt=0)
        .order_by("-asistencias", "id_jugador__apellido")[:10]
    )

    # -----------------------------------------------------
    # SANCIONES
    # -----------------------------------------------------

    sanciones = (
        estadisticas
        .filter(
            Q(tarjetas_amarillas__gt=0)
            | Q(tarjetas_rojas__gt=0)
        )
        .select_related(
            "id_jugador",
            "id_jugador__id_equipo",
            "id_partido",
            "id_partido__equipo_local",
            "id_partido__equipo_visitante",
        )
        .order_by(
            "-id_partido__fecha",
            "-id_partido__hora",
        )[:10]
    )

    resumen_sanciones = sanciones.aggregate(
        total_amarillas=Sum("tarjetas_amarillas"),
        total_rojas=Sum("tarjetas_rojas"),
    )

    total_amarillas = resumen_sanciones["total_amarillas"] or 0
    total_rojas = resumen_sanciones["total_rojas"] or 0

    # -----------------------------------------------------
    # TABLAS GENERALES DE POSICIONES
    # -----------------------------------------------------

    tablas_posiciones = []

    for campeonato in campeonatos_usuario:

        posiciones = _obtener_tabla_posiciones(
            campeonato,
            equipos_usuario_ids,
        )

        tablas_posiciones.append({
            "campeonato": campeonato,
            "equipos": posiciones,
        })

    # -----------------------------------------------------
    # CONTEXTO
    # -----------------------------------------------------

    contexto = {
        "equipos": equipos_usuario,
        "total_equipos": total_equipos,

        "jugadores": jugadores_usuario,
        "total_jugadores": total_jugadores,
        "total_jugadores_estadisticas": total_jugadores_estadisticas,

        "campeonatos": campeonatos_usuario,
        "total_campeonatos": total_campeonatos,

        "partidos": partidos,
        "total_partidos": total_partidos,

        "estadisticas": estadisticas,
        "total_goles": total_goles,
        "total_asistencias": total_asistencias,

        "goleadores": goleadores,
        "asistidores": asistidores,

        "sanciones": sanciones,
        "total_amarillas": total_amarillas,
        "total_rojas": total_rojas,

        "tablas_posiciones": tablas_posiciones,

        "hoy": hoy,
    }

    if total_equipos == 0:
        messages.info(
            request,
            "¡Bienvenido a CHAMPMANAGER! "
            "Todavía no tienes equipos registrados."
        )

    return render(request, "index.html", contexto)
