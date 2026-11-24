
from django.contrib import admin
from django.urls import path
from champmanageAPP import views

urlpatterns = [
    # AUTENTICACIÓN
    path("iniciar-sesion/", views.iniciar_sesion, name="login"),
    path("registrarse/", views.registrarse, name="registrarse"),
    path("cerrar-sesion/", views.cerrar_sesion, name="logout"),

    # ADMINISTRADOR DE DJANGO
    path("admin/", admin.site.urls),

    # INICIO DE DELEGADOS
    path("", views.index, name="index"),

    # INICIO DEL ADMINISTRADOR
    path("inicio-admin/", views.indexadmin, name="indexadmin"),

    # PANEL PERSONALIZADO
    path("panel/", views.panel_admin, name="admin_panel"),

    # CAMPEONATOS
    path("campeonatos/", views.lista_campeonatos, name="campeonatos"),
    path("campeonatos/crear/", views.crear_campeonato, name="crear_campeonato"),
    path("campeonatos/editar/<int:pk>/", views.editar_campeonato, name="editar_campeonato"),
    path("campeonatos/eliminar/<int:pk>/", views.eliminar_campeonato, name="eliminar_campeonato"),

    # SOLICITUDES DE INSCRIPCIÓN
    path(
        "campeonatos/<int:pk>/solicitar/",
        views.solicitar_campeonato,
        name="solicitar_campeonato"
    ),
    path(
        "solicitudes-campeonato/",
        views.lista_solicitudes,
        name="solicitudes_campeonato"
    ),
    path(
        "solicitudes-campeonato/<int:pk>/gestionar/",
        views.gestionar_solicitud,
        name="gestionar_solicitud"
    ),

    # EQUIPOS
    path("equipos/", views.lista_equipos, name="equipos"),
    path("equipos/crear/", views.crear_equipo, name="crear_equipo"),
    path("equipos/editar/<int:pk>/", views.editar_equipo, name="editar_equipo"),
    path("equipos/eliminar/<int:pk>/", views.eliminar_equipo, name="eliminar_equipo"),

    # JUGADORES
    path("jugadores/", views.lista_jugadores, name="jugadores"),
    path("jugadores/crear/", views.crear_jugador, name="crear_jugador"),
    path("jugadores/editar/<int:pk>/", views.editar_jugador, name="editar_jugador"),
    path("jugadores/eliminar/<int:pk>/", views.eliminar_jugador, name="eliminar_jugador"),

    # PARTIDOS
    path("partidos/", views.lista_partidos, name="partidos"),
    path("partidos/crear/", views.crear_partido, name="crear_partido"),
    path("partidos/editar/<int:pk>/", views.editar_partido, name="editar_partido"),
    path("partidos/eliminar/<int:pk>/", views.eliminar_partido, name="eliminar_partido"),
    path(
        "partidos/<int:pk>/gestionar-evento/",
        views.gestionar_evento_partido,
        name="gestionar_evento_partido"
    ),

    # ESTADÍSTICAS
    path("estadisticas/", views.lista_estadisticas, name="estadisticas"),
    path("estadisticas/crear/", views.crear_estadistica, name="crear_estadistica"),
    path("estadisticas/editar/<int:pk>/", views.editar_estadistica, name="editar_estadistica"),
    path("estadisticas/eliminar/<int:pk>/", views.eliminar_estadistica, name="eliminar_estadistica"),

    # SANCIONES
    path("sanciones/", views.sanciones, name="sanciones"),
    path("sanciones/registrar/", views.registrar_sancion, name="registrar_sancion"),
    path("sanciones/editar/<int:pk>/", views.editar_sancion, name="editar_sancion"),
    path("sanciones/eliminar/<int:pk>/", views.eliminar_sancion, name="eliminar_sancion"),
]
