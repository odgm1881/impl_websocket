import asyncio
import os
import struct

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
        is_client: bool,
    ) -> None:
        self.reader = reader
        self.writer = writer
        self.is_client = is_client
        self.close_sent = False
        self.got_pong = False
        self.last_ping_payload = None

    async def run(self):
        pass

    async def send_message(
        self,
        payload: bytes,
        opcode: int = 1,
        max_frame_size: int = 65535,
    ):
        mask = self.is_client
        payload_len = len(payload)

        if payload_len <= max_frame_size:
            await self._send_frame(
                FrameInput(
                    fin=True,
                    opcode=opcode,
                    mask=mask,
                    payload_len=payload_len,
                    payload=payload,
                )
            )
            return

        offset = 0
        first = True

        while offset < payload_len:
            chunk_size = min(max_frame_size, payload_len - offset)
            chunk = payload[offset:offset + chunk_size]

            is_last = offset + chunk_size >= payload_len

            await self._send_frame(
                FrameInput(
                    fin=1 if is_last else 0,
                    opcode=opcode if first else 0,
                    mask=mask,
                    payload_len=len(chunk),
                    payload=chunk,
                )
            )

            offset += chunk_size

            if first:
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
                await self._handle_control_frame(frame)

            if frame.fin == 1 and frame.opcode not in control_opcodes:
                break

        if opcode == 1:
            full_payload = b"".join(f.payload for f in fragments)
            try:
                full_payload.decode("utf-8")
            except UnicodeDecodeError:
                await self._send_close(
                    code=1007, reason="Invalid UTF-8", fail=True
                )
                raise Exception("Invalid UTF-8 in text frame")

        return fragments

    async def run_heartbeat(self, interval: int = 30):
        while not self.close_sent:
            try:
                self.last_ping_payload = os.urandom(4)
                self.got_pong = False

                await self._send_ping(self.last_ping_payload)

                await asyncio.sleep(interval)

                if not self.got_pong:
                    print("No pong received, closing connection")
                    await self._send_close()
                    self.close_sent = True
                    return

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

        first_byte = bytes([(frame.fin << 7) | frame.opcode])
        second_byte = bytes([(frame.mask << 7) | indicator])

        self.writer.write(first_byte + second_byte)
        await self.writer.drain()

        if indicator == 126:
            self.writer.write(struct.pack("!H", frame.payload_len))
            await self.writer.drain()
        elif indicator == 127:
            self.writer.write(struct.pack("!Q", frame.payload_len))
            await self.writer.drain()

        masked_payload = None

        if frame.mask:
            masking_key = os.urandom(4)
            self.writer.write(masking_key)
            await self.writer.drain()

            masked_payload = bytes(
                b ^ masking_key[i % 4] for i, b in enumerate(frame.payload)
            )

        self.writer.write(frame.payload if not frame.mask else masked_payload)
        await self.writer.drain()

    async def _read_frame(self) -> FrameInput:
        header = await recv_exact(self.reader, 2)
        first_byte, second_byte = struct.unpack("!BB", header)

        fin = first_byte >> 7
        rsv = (first_byte >> 4) & 0x07
        opcode = first_byte & 0x0F
        mask = second_byte >> 7

        if rsv != 0:
            raise Exception(f"Reserved bits must be 0, got RSV={rsv}")

        valid_opcodes = {0, 1, 2, 8, 9, 10}
        if opcode not in valid_opcodes:
            raise Exception(f"Reserved opcode: {opcode}")
        payload_len = second_byte & 0x7F
        if payload_len == 126:
            exc = await recv_exact(self.reader, 2)
            payload_len = struct.unpack("!H", exc)[0]
        elif payload_len == 127:
            exc = await recv_exact(self.reader, 8)
            payload_len = struct.unpack("!Q", exc)[0]

        expected_mask = not self.is_client
        if bool(mask) != expected_mask:
            raise Exception(
                "Unmasked frame from client" if not self.is_client
                else "Masked frame from server"
            )

        masking_key = None

        if mask:
            masking_key = await recv_exact(self.reader, 4)

        payload = await recv_exact(self.reader, payload_len)

        if mask:
            payload = bytes(
                b ^ masking_key[i % 4] for i, b in enumerate(payload)
            )

        return FrameInput(
            fin=fin,
            mask=mask,
            opcode=opcode,
            payload_len=payload_len,
            payload=payload,
        )

    async def _handle_control_frame(self, frame: FrameInput) -> None:
        if frame.fin != 1:
            raise Exception("Control frame fin should be 1")

        if len(frame.payload) > 125:
            raise Exception("Control frame payload too big")

        if frame.opcode == 10:
            if frame.payload == self.last_ping_payload:
                self.got_pong = True

        if frame.opcode == 9:
            await self._send_pong(frame.payload)

        if frame.opcode == 8:
            await self._handle_close_frame(frame)

    async def _handle_close_frame(self, frame: FrameInput) -> None:
        code = reason = None

        if frame.payload_len == 1:
            await self._send_close(
                code=1002, reason="Invalid close frame payload", fail=True
            )
            return

        if frame.payload_len >= 2:
            code = struct.unpack("!H", frame.payload[:2])[0]

            prohibited = {1004, 1005, 1006}
            if code < 1000 or code in prohibited or 1012 <= code <= 2999:
                await self._send_close(
                    code=1002, reason="Invalid close code", fail=True
                )
                return

            if frame.payload_len > 2:
                try:
                    reason = frame.payload[2:].decode("utf-8")
                except UnicodeDecodeError:
                    await self._send_close(
                        code=1007,
                        reason="Invalid UTF-8 in close reason",
                        fail=True,
                    )
                    return

        if not self.close_sent:
            await self._send_close(code=code or 1000, reason=reason or "")
            self.close_sent = True

        self.writer.close()
        await self.writer.wait_closed()

    async def _send_ping(self, payload: bytes = b""):
        await self._send_frame(
            FrameInput(
                fin=1,
                opcode=9,
                mask=self.is_client,
                payload_len=len(payload),
                payload=payload,
            )
        )

    async def _send_pong(self, payload: bytes = b""):
        await self._send_frame(
            FrameInput(
                fin=1,
                opcode=10,
                mask=self.is_client,
                payload_len=len(payload),
                payload=payload,
            )
        )

    async def _send_close(
        self, code: int | None = 1000, reason: str = "", *, fail: bool = False
    ):
        payload = b""

        if code is not None:
            payload = struct.pack("!H", code)
            if reason:
                payload += reason.encode("utf-8")

        await self._send_frame(
            FrameInput(
                fin=1,
                opcode=8,
                mask=self.is_client,
                payload_len=len(payload),
                payload=payload,
            )
        )

        if fail:
            self.close_sent = True
            self.writer.close()
            await self.writer.wait_closed()
