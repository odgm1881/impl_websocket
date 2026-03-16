import asyncio
import socket

from typing import Tuple
from enum import Enum
from dataclasses import dataclass


class WebSocketState(Enum):
    CONNECTING = 0
    OPEN = 1
    CLOSING = 2
    CLOSED = 3


@dataclass
class Connection:
    client_socket: socket.socket
    state: WebSocketState
    server_host: str
    server_port: int


@dataclass
class FrameInput:
    fin: bool
    mask: bool
    opcode: int
    payload_len: int
    payload: bytes


@dataclass
class FrameOutput:
    opcode: int
    payload: bytes