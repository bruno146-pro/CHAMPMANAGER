
from django.db import models
from django.contrib.auth.models import User


class Campeonato(models.Model):
    id_campeonato = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=100)
    fecha_inicio = models.DateField()
    fecha_termino = models.DateField()
    estado = models.CharField(max_length=20, default="planificación")

    class Meta:
        db_table = "campeonato"

    def __str__(self):
        return self.nombre


class Equipo(models.Model):
    id_equipo = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=100)
    delegado = models.CharField(max_length=100)

    usuario_delegado = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="equipos_delegados"
    )

    id_campeonato = models.ForeignKey(
        Campeonato,
        on_delete=models.SET_NULL,
        db_column="id_campeonato",
        null=True,
        blank=True
    )

    class Meta:
        db_table = "equipo"

    def __str__(self):
        return self.nombre


class InscripcionEquipo(models.Model):
    equipo = models.ForeignKey(
        Equipo,
        on_delete=models.CASCADE,
        related_name="inscripciones"
    )

    campeonato = models.ForeignKey(
        Campeonato,
        on_delete=models.CASCADE,
        related_name="inscripciones"
    )

    fecha_inscripcion = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "inscripcion_equipo"
        constraints = [
            models.UniqueConstraint(
                fields=["equipo", "campeonato"],
                name="uq_inscripcion_equipo_campeonato"
            )
        ]

    def __str__(self):
        return f"{self.equipo} - {self.campeonato}"


class SolicitudCampeonato(models.Model):
    ESTADOS = [
        ("pendiente", "Pendiente"),
        ("aprobada", "Aprobada"),
        ("rechazada", "Rechazada"),
    ]

    equipo = models.ForeignKey(
        Equipo,
        on_delete=models.CASCADE,
        related_name="solicitudes_campeonato"
    )

    campeonato = models.ForeignKey(
        Campeonato,
        on_delete=models.CASCADE,
        related_name="solicitudes"
    )

    usuario = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="solicitudes_campeonato"
    )

    estado = models.CharField(
        max_length=20,
        choices=ESTADOS,
        default="pendiente"
    )

    fecha_solicitud = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "solicitud_campeonato"
        constraints = [
            models.UniqueConstraint(
                fields=["equipo", "campeonato"],
                name="uq_solicitud_equipo_campeonato"
            )
        ]

    def __str__(self):
        return f"{self.equipo} - {self.campeonato} ({self.estado})"


class Jugador(models.Model):
    id_jugador = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=80)
    apellido = models.CharField(max_length=80)
    numero_camiseta = models.IntegerField(null=True, blank=True)

    id_equipo = models.ForeignKey(
        Equipo,
        on_delete=models.CASCADE,
        db_column="id_equipo"
    )

    class Meta:
        db_table = "jugador"

    def __str__(self):
        return f"{self.nombre} {self.apellido}"


class Partido(models.Model):

    ESTADOS = [
        ("programado", "Programado"),
        ("en_juego", "En juego"),
        ("descanso", "Descanso"),
        ("finalizado", "Finalizado"),
    ]

    PERIODOS = [
        ("primer_tiempo", "Primer tiempo"),
        ("segundo_tiempo", "Segundo tiempo"),
        ("alargue_primer_tiempo", "Primer tiempo del alargue"),
        ("alargue_segundo_tiempo", "Segundo tiempo del alargue"),
    ]

    id_partido = models.AutoField(primary_key=True)

    fecha = models.DateField()
    hora = models.TimeField()

    resultado_local = models.IntegerField(default=0)
    resultado_visitante = models.IntegerField(default=0)

    estado = models.CharField(
        max_length=20,
        choices=ESTADOS,
        default="programado"
    )

    # Permite saber exactamente en qué tiempo está el encuentro.
    periodo = models.CharField(
        max_length=30,
        choices=PERIODOS,
        default="primer_tiempo"
    )

    id_campeonato = models.ForeignKey(
        Campeonato,
        on_delete=models.CASCADE,
        db_column="id_campeonato"
    )

    equipo_local = models.ForeignKey(
        Equipo,
        on_delete=models.CASCADE,
        related_name="partidos_locales",
        db_column="equipo_local"
    )

    equipo_visitante = models.ForeignKey(
        Equipo,
        on_delete=models.CASCADE,
        related_name="partidos_visitantes",
        db_column="equipo_visitante"
    )

    class Meta:
        db_table = "partido"

    def __str__(self):
        return (
            f"{self.equipo_local} vs. {self.equipo_visitante} "
            f"({self.fecha})"
        )


class EventoPartido(models.Model):

    TIPOS_EVENTO = [
        ("iniciar", "Inicio del partido"),
        ("gol_local", "Gol del equipo local"),
        ("gol_visitante", "Gol del equipo visitante"),
        ("tarjeta_amarilla", "Tarjeta amarilla"),
        ("tarjeta_roja", "Tarjeta roja"),

        ("fin_primer_tiempo", "Final del primer tiempo"),
        ("iniciar_segundo_tiempo", "Inicio del segundo tiempo"),
        ("fin_segundo_tiempo", "Final del segundo tiempo"),

        ("iniciar_alargue_primer_tiempo", "Inicio del primer tiempo del alargue"),
        ("fin_alargue_primer_tiempo", "Final del primer tiempo del alargue"),
        ("iniciar_alargue_segundo_tiempo", "Inicio del segundo tiempo del alargue"),

        ("partido_finalizado", "Partido finalizado"),
    ]

    id_evento = models.AutoField(primary_key=True)

    partido = models.ForeignKey(
        Partido,
        on_delete=models.CASCADE,
        related_name="eventos"
    )

    jugador = models.ForeignKey(
        Jugador,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="eventos_partido"
    )

    tipo = models.CharField(
        max_length=40,
        choices=TIPOS_EVENTO
    )

    minuto = models.PositiveSmallIntegerField(
        null=True,
        blank=True
    )

    descripcion = models.CharField(
        max_length=255,
        blank=True,
        default=""
    )

    fecha_hora = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "evento_partido"
        ordering = ["fecha_hora"]

    def __str__(self):
        if self.jugador:
            return (
                f"{self.get_tipo_display()} - "
                f"{self.jugador} - {self.partido}"
            )

        return f"{self.get_tipo_display()} - {self.partido}"


class Estadistica(models.Model):

    id_estadistica = models.AutoField(primary_key=True)

    id_partido = models.ForeignKey(
        Partido,
        on_delete=models.CASCADE,
        db_column="id_partido"
    )

    id_jugador = models.ForeignKey(
        Jugador,
        on_delete=models.CASCADE,
        db_column="id_jugador"
    )

    goles = models.PositiveIntegerField(default=0)
    asistencias = models.PositiveIntegerField(default=0)
    tarjetas_amarillas = models.PositiveIntegerField(default=0)
    tarjetas_rojas = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "estadistica"
        constraints = [
            models.UniqueConstraint(
                fields=["id_partido", "id_jugador"],
                name="uq_estadistica_partido_jugador"
            )
        ]

    def __str__(self):
        return f"{self.id_jugador} - {self.goles} goles"


class PerfilUsuario(models.Model):

    ROLES = [
        ("delegado", "Delegado"),
        ("administrador", "Administrador"),
    ]

    usuario = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="perfil"
    )

    rol = models.CharField(
        max_length=20,
        choices=ROLES,
        default="delegado"
    )

    class Meta:
        db_table = "perfil_usuario"

    def __str__(self):
        return f"{self.usuario.username} - {self.rol}"
