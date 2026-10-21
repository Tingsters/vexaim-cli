"""Guard the optional diagnostic input against unknown/program menu screens."""

import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

spec = importlib.util.spec_from_file_location(
    "aim_idle", Path(__file__).with_name("probe-aim-idle.py")
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class IdleProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_input_is_rejected_on_every_nonhome_screen(self):
        system = SimpleNamespace(exchange=AsyncMock())
        display = SimpleNamespace(packet=lambda *_args: self.fail("Input encoded"))
        for screen in [None, -1, *range(1, 256), "0"]:
            self.assertFalse(await probe.home_back(system, display, screen))
        system.exchange.assert_not_awaited()

    async def test_lost_ack_is_not_replayed(self):
        system = SimpleNamespace(exchange=AsyncMock(side_effect=TimeoutError("lost")))
        display = SimpleNamespace(
            packet=lambda family, opcode, data: (family, opcode, data)
        )
        with self.assertRaises(TimeoutError):
            await probe.home_back(system, display, 0)
        system.exchange.assert_awaited_once_with((0x56, 0x65, b"\x54"))


if __name__ == "__main__":
    unittest.main()
