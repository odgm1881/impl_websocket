import secrets
import base64
import hashlib

from typing import Tuple


def _get_request(
    resource: str,
    host: str,
    port: str = "80",
) -> str:
    host_header = host if port == "80" else f"{host}:{port}"
    websocket_key = base64.b64encode(secrets.token_bytes(16)).decode()

    request = (
        f"GET /{resource} HTTP/1.1\r\n"
        f"Host: {host_header}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {websocket_key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )

    return request


def _get_response(accept_key: str) -> str:
    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept_key}\r\n"
        "\r\n"
    )

    return response


def _handle_request(request: str) -> Tuple[bool, str]:
    headers: dict[str, str] = {}

    first_header = request.split("\r\n", 1)[0].split()

    if first_header[0] != "GET" or first_header[2] != "HTTP/1.1":
        return False, ""

    for line in request.split("\r\n")[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()

    key_accept = _compute_accept_key(headers["sec-websocket-key"])

    return True, key_accept


def _handle_response(response: str, websocket_key: str) -> bool:
    headers: dict[str, str] = {}

    first_header = response.split("\r\n", 1)[0].split()

    if first_header[1] != "101":
        return False

    for line in response.split("\r\n")[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()

    valid_accept = _compute_accept_key(websocket_key)
    response_accept = headers["sec-websocket-accept"]

    if valid_accept != response_accept:
        return False

    return True


def _compute_accept_key(key: str) -> str:
    guid = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
    combined = key + guid
    sha1 = hashlib.sha1(combined.encode()).digest()
    return base64.b64encode(sha1).decode()
