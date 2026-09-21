"""Pair two authenticated netcat connections. Python 3.10+, no dependencies.

Run: python server.py
Connect two clients: nc SERVER_ADDRESS 4444
At each prompt enter the generated token. Everything after that is relayed.
This server does not execute commands or create a shell on either endpoint.
Plain TCP provides no encryption; use a trusted network or encrypted tunnel.
"""

import asyncio
import contextlib
import hmac
import secrets


class Broker:
    def __init__(self):
        self.token = secrets.token_urlsafe(24)
        self.waiting = None
        self.active = False
        self.connections = set()

    async def send(self, writer, data):
        writer.write(data)
        await asyncio.wait_for(writer.drain(), timeout=15)

    async def pump(self, reader, writer):
        while data := await reader.read(65536):
            await self.send(writer, data)

    async def handle(self, reader, writer):
        self.connections.add(writer)
        waiting = None
        owns_session = False
        peer_writer = None
        try:
            await self.send(writer, b"Access token: ")
            try:
                token = await asyncio.wait_for(reader.readline(), timeout=30)
            except (ValueError, asyncio.TimeoutError):
                return
            if not hmac.compare_digest(token.rstrip(b"\r\n"), self.token.encode()):
                await self.send(writer, b"Invalid token.\n")
                return
            if self.active:
                await self.send(writer, b"Broker busy; try again later.\n")
                return

            if self.waiting is None:
                done = asyncio.get_running_loop().create_future()
                session_done = asyncio.get_running_loop().create_future()
                waiting = (reader, writer, done, session_done)
                self.waiting = waiting
                await self.send(writer, b"Waiting for the second connection (120 seconds)...\n")
                # The pairing handler owns both streams until the session ends.
                await asyncio.wait_for(asyncio.shield(done), timeout=120)
                if done.result() == "paired":
                    await session_done
                return

            peer_reader, peer_writer, paired, session_done = self.waiting
            self.waiting = None
            self.active = True
            owns_session = True
            paired.set_result("paired")
            await self.send(peer_writer, b"Connected. Relaying bytes now.\n")
            await self.send(writer, b"Connected. Relaying bytes now.\n")
            tasks = [
                asyncio.create_task(self.pump(reader, peer_writer)),
                asyncio.create_task(self.pump(peer_reader, writer)),
            ]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        except (OSError, asyncio.TimeoutError):
            pass
        finally:
            if waiting is not None and self.waiting is waiting:
                self.waiting = None
            if owns_session:
                peer_writer.close()
                self.active = False
                if not session_done.done():
                    session_done.set_result(None)
            writer.close()
            with contextlib.suppress(OSError, asyncio.TimeoutError):
                await asyncio.wait_for(writer.wait_closed(), timeout=5)
            self.connections.discard(writer)


async def main():
    broker = Broker()
    server = await asyncio.start_server(broker.handle, "0.0.0.0", 4444, limit=4096)
    print("TCP broker listening on 0.0.0.0:4444", flush=True)
    print(f"Access token: {broker.token}", flush=True)
    print("Connect two netcat clients and enter this token at each prompt.")
    print("Plaintext relay only; this program does not execute shell commands.")
    try:
        async with server:
            await server.serve_forever()
    finally:
        for writer in list(broker.connections):
            writer.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except OSError as exc:
        raise SystemExit(f"Cannot start broker: {exc}") from exc
