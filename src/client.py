import asyncio

import socketserver
from base import Connection, WebSocketState
from utils.frame import _parser_frame
from utils.http import _get_request, _handle_response


class WebSocketClient:
    def __init__(
        self, 
        reader: asyncio.StreamReader, 
        writer: asyncio.StreamWriter, 
        connection: Connection, 
        resource: str
    ) -> None:
        self.reader = reader
        self.writer = writer
        self.connection = connection
        self.resource = resource

    async def run(self):
        ...

    async def handsnake(self) -> bool:
        request = _get_request(
            self.resource, 
            self.connection.server_host, 
            self.connection.server_port
        )

        self.writer.write(request)
        await self.writer.drain()

        response = await self.reader.read(1024)

        is_valid = _handle_response(response.decode())

        if is_valid:
            self.connection.state = WebSocketState.OPEN
            return True

        self.writer.close()
        await self.writer.wait_closed()

        return False

    async def heartbeat(self, interval=30):
        ...