import asyncio

import secrets
import base64
import hashlib

key = base64.b64encode(secrets.token_bytes(16)).decode()


async def handle_client_request(resource, host, port):
    request = (
        f"GET {resource} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n"
        f"\r\n"
    )
    reader, writer = await asyncio.open_connection(host, port)
    writer.write(request.encode())

    await writer.drain()

    #######################################

    data = await reader.read(1024)
    request = data.decode("utf-8")

    headers: dict[str, str] = {}

    for line in request.split("\r\n")[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()


GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def compute_accept_key(key: str) -> str:
    combined = key + GUID
    sha1 = hashlib.sha1(combined.encode()).digest()

    return base64.b64encode(sha1).decode()


accept_key = compute_accept_key(key)


async def handle_server_response(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
):
    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept_key}\r\n"
        "\r\n"
    )

    writer.write(response.encode())
    await writer.drain()
