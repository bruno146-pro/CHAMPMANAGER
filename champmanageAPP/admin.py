
from django.contrib import admin
from .models import Campeonato, Equipo, Jugador, Partido, Estadistica


@admin.register(Campeonato)
class CampeonatoAdmin(admin.ModelAdmin):
    list_display = (
        "id_campeonato",
        "nombre",
        "fecha_inicio",
        "fecha_termino",
        "estado",
    )
    search_fields = ("nombre",)
    list_filter = ("estado", "fecha_inicio")
    ordering = ("-fecha_inicio",)


@admin.register(Equipo)
class EquipoAdmin(admin.ModelAdmin):
    list_display = (
        "id_equipo",
        "nombre",
        "delegado",
        "id_campeonato",
    )
    search_fields = ("nombre", "delegado")
    list_filter = ("id_campeonato",)
    ordering = ("nombre",)


@admin.register(Jugador)
class JugadorAdmin(admin.ModelAdmin):
    list_display = (
        "id_jugador",
        "nombre",
        "apellido",
        "numero_camiseta",
        "id_equipo",
    )
    search_fields = (
        "nombre",
        "apellido",
        "id_equipo__nombre",
    )
    list_filter = ("id_equipo",)
    ordering = ("apellido", "nombre")


@admin.register(Partido)
class PartidoAdmin(admin.ModelAdmin):
    list_display = (
        "id_partido",
        "fecha",
        "hora",
        "equipo_local",
        "resultado_local",
        "resultado_visitante",
        "equipo_visitante",
        "id_campeonato",
    )
    search_fields = (
        "equipo_local__nombre",
        "equipo_visitante__nombre",
        "id_campeonato__nombre",
    )
    list_filter = ("fecha", "id_campeonato")
    ordering = ("-fecha", "-hora")
    date_hierarchy = "fecha"


@admin.register(Estadistica)
class EstadisticaAdmin(admin.ModelAdmin):
    list_display = (
        "id_estadistica",
        "id_jugador",
        "id_partido",
        "goles",
        "asistencias",
        "tarjetas_amarillas",
        "tarjetas_rojas",
    )
    search_fields = (
        "id_jugador__nombre",
        "id_jugador__apellido",
        "id_jugador__id_equipo__nombre",
    )
    list_filter = (
        "tarjetas_amarillas",
        "tarjetas_rojas",
    )
    ordering = ("-goles", "-asistencias")
