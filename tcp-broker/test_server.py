import asyncio
import unittest
from server import Broker


class BrokerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.broker = Broker()
        self.clients = []
        self.servers = {}
        for role in ("sender", "receiver"):
            self.servers[role] = await asyncio.start_server(
                lambda r, w, role=role: self.broker.handle(r, w, role), "127.0.0.1", 0)

    async def asyncTearDown(self):
        for w in self.clients:
            w.close()
            await w.wait_closed()
        for s in self.servers.values():
            s.close()
            await s.wait_closed()

    async def connect(self, role):
        port = self.servers[role].sockets[0].getsockname()[1]
        r, w = await asyncio.open_connection("127.0.0.1", port)
        self.clients.append(w)
        if role == "sender":
            self.assertEqual(await asyncio.wait_for(r.readexactly(14), 2), b"Access token: ")
        return r, w

    async def line(self, r):
        return await asyncio.wait_for(r.readline(), 2)

    async def auth(self, w):
        w.write(self.broker.token.encode() + b"\n")
        await w.drain()

    async def pair(self, first):
        if first == "sender":
            sr, sw = await self.connect("sender")
            await self.auth(sw)
            self.assertIn(b"Waiting", await self.line(sr))
            xr, xw = await self.connect("sender")
            await self.auth(xw)
            self.assertIn(b"busy", await self.line(xr))
            rr, rw = await self.connect("receiver")
        else:
            rr, rw = await self.connect("receiver")
            sr, sw = await self.connect("sender")
            sw.write(b"wrong\n")
            await sw.drain()
            self.assertEqual(await self.line(sr), b"Invalid token.\n")
            self.assertEqual(await self.line(sr), b"")
            rw.write(b"early\x00")
            await rw.drain()
            sr, sw = await self.connect("sender")
            await self.auth(sw)
        self.assertEqual(await self.line(sr), b"Connected. Relaying bytes now.\n")
        if first == "receiver":
            self.assertEqual(await asyncio.wait_for(sr.readexactly(6), 2), b"early\x00")
        data = bytes(range(256)) * 512
        for writer, reader in ((sw, rr), (rw, sr)):
            writer.write(data)
            await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.readexactly(len(data)), 2), data)
        xr, xw = await self.connect("receiver")
        self.assertEqual(await self.line(xr), b"")
        xr, xw = await self.connect("sender")
        await self.auth(xw)
        self.assertIn(b"busy", await self.line(xr))
        rw.close()
        self.assertEqual(await self.line(sr), b"")
        for _ in range(20):
            if not self.broker.active:
                break
            await asyncio.sleep(0.01)
        self.assertFalse(self.broker.active)
        self.assertIsNone(self.broker.waiting)

    async def test_receiver_first_then_reuse(self):
        await self.pair("receiver")
        await self.pair("sender")

    async def test_sender_first(self):
        await self.pair("sender")


if __name__ == "__main__":
    unittest.main()
