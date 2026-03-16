import time
import asyncio
import struct
import os

from src.base import FrameInput, FrameOutput


async def recv_exact(reader: asyncio.StreamReader, length: int):
    data = b""

    while len(data) < length:
        chunk = await reader.read(length - len(data))
        if not chunk:
            raise ConnectionError("Connection is closed")
        data += chunk
    return data


class WebSocketBase:
    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self.reader = reader
        self.writer = writer

    async def run(self):
        pass

    async def send_message(
            self, 
            payload: bytes, 
            opcode: int = 1,
            mask: bool = False,
            max_frame_size: int = 65535
    ):
        payload_len = len(payload)

        if payload_len <= max_frame_size:
            await self._send_frame(FrameInput(
                fin=1,
                opcode=opcode,
                mask=mask,
                payload_len=payload_len,
                payload=payload
            ))
            return
        
        offset = 0
        first = True

        while offset < payload_len:
            chunk_size = min(max_frame_size, payload_len - offset)
            chunk = payload[offset:offset+chunk_size]
            
            is_last = (offset + chunk_size >= payload_len)

            await self._send_frame(FrameInput(
                fin=1 if is_last else 0,
                opcode=opcode if first else 0,
                mask=mask,
                payload_len=len(chunk),
                payload=chunk
            ))

            offset += chunk_size
            first = False 
        
    async def read_message(self) -> list[FrameOutput]:
        fragments = []
        opcode = None
        control_opcodes = {8, 9, 10}

        while True:
            frame = await self._read_frame()

            if opcode is None and frame.opcode == 0:
                raise Exception("Continuation frame without start")

            if opcode is not None:
                if frame.opcode not in control_opcodes and frame.opcode:
                    raise Exception("Expected continuation frame")

            if opcode is None and frame.opcode not in control_opcodes:
                opcode = frame.opcode

            if frame.opcode not in control_opcodes:
                fragments.append(
                    FrameOutput(
                        opcode=frame.opcode,
                        payload=frame.payload,
                    )
                )
            else:
                self._handle_control_frame(frame)

            if frame.fin == 1 and frame.opcode not in control_opcodes:
                break

        return fragments if len(fragments) > 1 else fragments[0]
    
    async def heartbreat(self, interval: int = 30):
        while True:
            try:
                await asyncio.sleep(interval)
                await self._send_ping()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Heartbeat error: {e}")
                break

    async def _send_frame(self, frame: FrameInput):
        if frame.payload_len < 126:
            indicator = frame.payload_len
        elif frame.payload_len <= 65535:
            indicator = 126
        else:
            indicator = 127

        first_byte = bytes((frame.fin << 7) | frame.opcode)
        second_byte = bytes((frame.mask << 7) | indicator)

        self.writer.write(first_byte + second_byte)
        await self.writer.drain()

        masked_payload = None

        if frame.mask:
            masking_key = os.urandom(4)
            self.writer.write(masking_key)
            await self.writer.drain()

            masked_payload = bytes(
                b ^ masking_key[i % 4] for i, b in enumerate(frame.payload)
            )

        if indicator == 126:
            payload_len = struct.pack("!H", frame.payload_len)
            self.writer.write(payload_len)
            await self.writer.drain()
        elif indicator == 127:
            payload_len = struct.pack("!Q", frame.payload_len)
            self.writer.write(payload_len)
            await self.writer.drain()

        self.writer.write(frame.payload if not frame.mask else masked_payload)
        await self.writer.drain()

    async def _read_frame(self) -> FrameInput:
        header = await recv_exact(self.reader, 2)
        first_byte, second_byte = struct.unpack("!BB", header)

        fin = first_byte >> 7
        opcode = first_byte & 0x0F
        mask = second_byte >> 7
        payload_len = second_byte & 0x7F
        masking_key = None

        if mask:
            masking_key = await recv_exact(self.reader, 4)

        if payload_len == 126:
            exc = await recv_exact(self.reader, 2)
            payload_len = struct.unpack("!H", exc)[0]
        elif payload_len == 127:
            exc = await recv_exact(self.reader, 8)
            payload_len = struct.unpack("!Q", exc)[0]

        payload = await recv_exact(self.reader, payload_len)

        if mask:
            payload = bytes(b ^ masking_key[i % 4] for i, b in enumerate(payload))

        return FrameInput(
            fin=fin,
            opcode=opcode,
            payload_len=payload_len,
            payload=payload,
        )

    async def _handle_control_frame(self, frame: FrameInput) -> None:
        if len(frame.payload) > 125:
            raise Exception("Control frame payload too big")

        if frame.opcode == 9:
            ...

        if frame.opcode == 8:
            ...

        if frame.opcode == 10:
            ...

    async def _send_ping(self, payload: bytes = b""):
        await self._send_frame(FrameInput(
            fin=1,
            opcode=9,
            mask=False,
            payload_len=len(payload),
            payload=payload
        ))

    async def _send_pong(self, payload: bytes = b""):
        await self._send_frame(FrameInput(
            fin=1,
            opcode=10,
            mask=False,
            payload_len=len(payload),
            payload=payload
        ))