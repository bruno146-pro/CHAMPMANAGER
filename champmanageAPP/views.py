from functools import wraps

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.forms import modelform_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .models import (
    Campeonato,
    Equipo,
    Estadistica,
    Jugador,
    Partido,
)


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
    form = Formulario(request.POST or None, instance=instancia)

    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                form.save()

            messages.success(
                request,
                "Registro guardado correctamente.",
            )
            return redirect(nombre_url)

        except IntegrityError:
            messages.error(
                request,
                "No se pudo guardar el registro. "
                "Comprueba los datos y las relaciones existentes.",
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
            f"{descripcion} eliminado correctamente.",
        )

    except IntegrityError:
        messages.error(
            request,
            f"No se pudo eliminar {descripcion.lower()} "
            "porque tiene registros relacionados.",
        )

    return redirect(nombre_url)


def admin_required(vista):
    """Permite el acceso únicamente a administradores autenticados."""

    @wraps(vista)
    @login_required(login_url="login")
    def comprobar_permisos(request, *args, **kwargs):
        if not request.user.is_staff:
            messages.error(
                request,
                "No tienes permisos para acceder a esa sección.",
            )
            return redirect("index")

        return vista(request, *args, **kwargs)

    return comprobar_permisos


# =========================================================
# INICIO
# =========================================================

def index(request):
    """Página principal de CHAMPMANAGER."""

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
        .order_by("-id_partido__fecha", "-id_partido__hora")[:10]
    )

    contexto = {
        "total_campeonatos": Campeonato.objects.count(),
        "total_equipos": Equipo.objects.count(),
        "total_jugadores": Jugador.objects.count(),
        "total_partidos": Partido.objects.count(),
        "campeonato_activo": Campeonato.objects.first(),

        "equipos": (
            Equipo.objects
            .select_related("id_campeonato")
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
        "total_jugadores_estadisticas": total_jugadores_estadisticas,
        "goleadores": goleadores,
        "asistidores": asistidores,
        "sanciones": sanciones_registradas,
    }

    return render(request, "index.html", contexto)


# =========================================================
# CAMPEONATOS
# =========================================================

def lista_campeonatos(request):
    """Muestra campeonatos y sus estadísticas."""

    campeonatos = (
        Campeonato.objects
        .annotate(total_equipos=Count("equipo"))
        .order_by("-fecha_inicio")
    )

    contexto = {
        "campeonatos": campeonatos,
        "total_campeonatos": Campeonato.objects.count(),

        "total_en_curso": Campeonato.objects.filter(
            Q(estado__iexact="en_curso")
            | Q(estado__iexact="En curso")
        ).count(),

        "total_planificados": Campeonato.objects.filter(
            Q(estado__iexact="planificacion")
            | Q(estado__iexact="planificación")
            | Q(estado__iexact="planificado")
            | Q(estado__iexact="Planificación")
        ).count(),

        "total_finalizados": Campeonato.objects.filter(
            Q(estado__iexact="finalizado")
        ).count(),
    }

    return render(request, "campeonatos.html", contexto)


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

def lista_equipos(request):
    """Muestra equipos y sus estadísticas."""

    contexto = {
        "equipos": (
            Equipo.objects
            .select_related("id_campeonato")
            .annotate(total_jugadores=Count("jugador"))
            .order_by("nombre")
        ),
        "campeonatos": Campeonato.objects.order_by("nombre"),
        "total_equipos": Equipo.objects.count(),
        "total_jugadores": Jugador.objects.count(),
        "total_campeonatos": Campeonato.objects.count(),
    }

    return render(request, "equipos.html", contexto)


def crear_equipo(request):
    """Registra un equipo nuevo."""

    contexto = {
        "campeonatos": Campeonato.objects.order_by("nombre"),
    }

    return _guardar_modelo(
        request,
        Equipo,
        ["nombre", "delegado", "id_campeonato"],
        "crear_equipos.html",
        contexto,
        "equipos",
    )


def editar_equipo(request, pk):
    """Actualiza un equipo existente."""

    equipo = get_object_or_404(Equipo, pk=pk)

    contexto = {
        "equipo": equipo,
        "campeonatos": Campeonato.objects.order_by("nombre"),
    }

    return _guardar_modelo(
        request,
        Equipo,
        ["nombre", "delegado", "id_campeonato"],
        "editar_equipos.html",
        contexto,
        "equipos",
        instancia=equipo,
    )


@require_POST
def eliminar_equipo(request, pk):
    """Elimina un equipo mediante POST."""

    equipo = get_object_or_404(Equipo, pk=pk)

    return _eliminar_modelo(
        request,
        equipo,
        "equipos",
        "Equipo",
    )


# =========================================================
# JUGADORES
# =========================================================

def lista_jugadores(request):
    """Muestra el listado de jugadores."""

    contexto = {
        "jugadores": (
            Jugador.objects
            .select_related("id_equipo")
            .order_by("apellido", "nombre")
        ),
        "equipos": Equipo.objects.order_by("nombre"),
        "total_jugadores": Jugador.objects.count(),
    }

    return render(request, "jugadores.html", contexto)


def crear_jugador(request):
    """Registra un jugador nuevo."""

    contexto = {
        "equipos": Equipo.objects.order_by("nombre"),
    }

    return _guardar_modelo(
        request,
        Jugador,
        ["nombre", "apellido", "numero_camiseta", "id_equipo"],
        "crear_jugador.html",
        contexto,
        "jugadores",
    )


def editar_jugador(request, pk):
    """Actualiza un jugador existente."""

    jugador = get_object_or_404(Jugador, pk=pk)

    contexto = {
        "jugador": jugador,
        "equipos": Equipo.objects.order_by("nombre"),
    }

    return _guardar_modelo(
        request,
        Jugador,
        ["nombre", "apellido", "numero_camiseta", "id_equipo"],
        "editar_jugador.html",
        contexto,
        "jugadores",
        instancia=jugador,
    )


@require_POST
def eliminar_jugador(request, pk):
    """Elimina un jugador mediante POST."""

    jugador = get_object_or_404(Jugador, pk=pk)

    return _eliminar_modelo(
        request,
        jugador,
        "jugadores",
        "Jugador",
    )


# =========================================================
# PARTIDOS
# =========================================================

def lista_partidos(request):
    """Muestra los partidos registrados."""

    partidos = (
        Partido.objects
        .select_related(
            "id_campeonato",
            "equipo_local",
            "equipo_visitante",
        )
        .order_by("-fecha", "-hora")
    )

    contexto = {
        "partidos": partidos,
        "total_partidos": partidos.count(),
        "campeonatos": Campeonato.objects.order_by("nombre"),
        "equipos": Equipo.objects.order_by("nombre"),
    }

    return render(request, "partidos.html", contexto)


def crear_partido(request):
    """Registra un partido nuevo."""

    contexto = {
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
        "crear_partido.html",
        contexto,
        "partidos",
    )


def editar_partido(request, pk):
    """Actualiza un partido existente."""

    partido = get_object_or_404(Partido, pk=pk)

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


@require_POST
def eliminar_partido(request, pk):
    """Elimina un partido mediante POST."""

    partido = get_object_or_404(Partido, pk=pk)

    return _eliminar_modelo(
        request,
        partido,
        "partidos",
        "Partido",
    )


# =========================================================
# ESTADÍSTICAS
# =========================================================

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


def crear_estadistica(request):
    """Registra las estadísticas de un jugador en un partido."""

    contexto = {
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


def editar_estadistica(request, pk):
    """Actualiza las estadísticas de un jugador."""

    estadistica = get_object_or_404(Estadistica, pk=pk)

    contexto = {
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
        .order_by("-id_partido__fecha", "-id_partido__hora")
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
            .order_by("id_equipo__nombre", "apellido", "nombre")
        ),
        "sanciones": registros,
        "equipos": Equipo.objects.order_by("nombre"),
    }

    return render(request, "sanciones.html", contexto)


# =========================================================
# SANCIONES: REGISTRAR
# =========================================================

@require_POST
def registrar_sancion(request):
    """Registra o actualiza las tarjetas de un jugador."""

    jugador_id = request.POST.get("id_jugador", "").strip()
    partido_id = request.POST.get("id_partido", "").strip()

    if not jugador_id or not partido_id:
        messages.error(
            request,
            "Debes seleccionar un partido y un jugador.",
        )
        return redirect("sanciones")

    try:
        amarillas = int(request.POST.get("tarjetas_amarillas", "0"))
        rojas = int(request.POST.get("tarjetas_rojas", "0"))
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
            "selecciona un jugador y partido válidos.",
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
            "El jugador debe pertenecer a uno de los equipos del partido.",
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
            "No fue posible guardar la sanción. Revisa la base de datos.",
        )
        return redirect("sanciones")

    if creado:
        messages.success(request, "Sanción registrada correctamente.")
    else:
        messages.success(request, "Sanción actualizada correctamente.")

    return redirect("sanciones")


# =========================================================
# SANCIONES: EDITAR
# =========================================================

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
                "La sanción se actualizó correctamente.",
            )
            return redirect("sanciones")

        except (TypeError, ValueError):
            messages.error(
                request,
                "Ingresa cantidades enteras no negativas.",
            )

    return render(
        request,
        "editar_sancion.html",
        {"sancion": sancion},
    )


# =========================================================
# SANCIONES: ELIMINAR
# =========================================================

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
        "La sanción se eliminó correctamente.",
    )
    return redirect("sanciones")


# =========================================================
# PANEL ADMINISTRATIVO PERSONALIZADO
# =========================================================

@admin_required
@never_cache
def panel_admin(request):
    """Dashboard personalizado para administradores."""

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
    """Autentica usuarios y redirige según sus permisos."""

    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect("panel_admin")
        return redirect("index")

    formulario = AuthenticationForm(
        request,
        data=request.POST or None,
    )

    if request.method == "POST" and formulario.is_valid():
        usuario = formulario.get_user()
        login(request, usuario)

        messages.success(
            request,
            f"Bienvenido, {usuario.username}.",
        )

        if usuario.is_staff:
            return redirect("panel_admin")

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
    """Crea una cuenta nueva para un usuario normal."""

    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect("panel_admin")
        return redirect("index")

    formulario = UserCreationForm(request.POST or None)

    if request.method == "POST" and formulario.is_valid():
        try:
            with transaction.atomic():
                usuario = formulario.save(commit=False)

                # Las cuentas registradas desde el formulario
                # no obtienen privilegios administrativos.
                usuario.is_staff = False
                usuario.is_superuser = False
                usuario.is_active = True
                usuario.save()

            login(request, usuario)

            messages.success(
                request,
                "Tu cuenta de delegado fue creada correctamente.",
            )

            return redirect("index")

        except IntegrityError:
            messages.error(
                request,
                "No se pudo crear la cuenta. Inténtalo nuevamente.",
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
        "Has cerrado sesión correctamente.",
    )

    return redirect("login")