
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async

from django.db.models import Q

from .models import Partido


class PartidoConsumer(AsyncJsonWebsocketConsumer):

    async def connect(self):
        self.partido_id = self.scope["url_route"]["kwargs"]["partido_id"]
        self.grupo = f"partido_{self.partido_id}"

        usuario = self.scope["user"]

        if not usuario.is_authenticated:
            await self.close()
            return

        tiene_permiso = await self.verificar_acceso(usuario)

        if not tiene_permiso:
            await self.close(code=4403)
            return

        await self.channel_layer.group_add(
            self.grupo,
            self.channel_name
        )

        await self.accept()

        await self.send_json({
            "tipo": "conexion",
            "mensaje": "Conectado a las notificaciones del partido."
        })

    async def disconnect(self, close_code):
        if hasattr(self, "grupo"):
            await self.channel_layer.group_discard(
                self.grupo,
                self.channel_name
            )

    @database_sync_to_async
    def verificar_acceso(self, usuario):
        if usuario.is_staff:
            return Partido.objects.filter(
                pk=self.partido_id
            ).exists()

        return Partido.objects.filter(
            Q(equipo_local__usuario_delegado=usuario) |
            Q(equipo_visitante__usuario_delegado=usuario),
            pk=self.partido_id
        ).exists()

    async def partido_actualizado(self, event):
        await self.send_json(event["data"])
