
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
    id_campeonato = models.ForeignKey(
        Campeonato,
        on_delete=models.CASCADE,
        db_column="id_campeonato",
    )

    class Meta:
        db_table = "equipo"

    def __str__(self):
        return self.nombre


class Jugador(models.Model):
    id_jugador = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=80)
    apellido = models.CharField(max_length=80)
    numero_camiseta = models.IntegerField(null=True, blank=True)
    id_equipo = models.ForeignKey(
        Equipo,
        on_delete=models.CASCADE,
        db_column="id_equipo",
    )

    class Meta:
        db_table = "jugador"

    def __str__(self):
        return f"{self.nombre} {self.apellido}"


class Partido(models.Model):
    id_partido = models.AutoField(primary_key=True)
    fecha = models.DateField()
    hora = models.TimeField()
    resultado_local = models.IntegerField(default=0)
    resultado_visitante = models.IntegerField(default=0)
    id_campeonato = models.ForeignKey(
        Campeonato,
        on_delete=models.CASCADE,
        db_column="id_campeonato",
    )
    equipo_local = models.ForeignKey(
        Equipo,
        on_delete=models.CASCADE,
        related_name="partidos_locales",
        db_column="equipo_local",
    )
    equipo_visitante = models.ForeignKey(
        Equipo,
        on_delete=models.CASCADE,
        related_name="partidos_visitantes",
        db_column="equipo_visitante",
    )

    class Meta:
        db_table = "partido"

    def __str__(self):
        return (
            f"{self.equipo_local} vs. {self.equipo_visitante} "
            f"({self.fecha})"
        )


class Estadistica(models.Model):
    id_estadistica = models.AutoField(primary_key=True)
    id_partido = models.ForeignKey(
        Partido,
        on_delete=models.CASCADE,
        db_column="id_partido",
    )
    id_jugador = models.ForeignKey(
        Jugador,
        on_delete=models.CASCADE,
        db_column="id_jugador",
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
                name="uq_estadistica_partido_jugador",
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
        related_name="perfil",
    )
    rol = models.CharField(
        max_length=20,
        choices=ROLES,
        default="delegado",
    )

    class Meta:
        db_table = "perfil_usuario"

    def __str__(self):
        return f"{self.usuario.username} - {self.rol}"
