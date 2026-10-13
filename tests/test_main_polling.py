# -*- coding: utf-8 -*-
"""آزمون حلقه دریافت پیام main: پردازش آپدیت و توقف تمیز، بدون شبکه."""
import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import main as main_module
from config import Settings
from handlers import build_dispatcher
from storage import Storage
from test_handlers import FakeBot, make_update


class PollFakeBot(FakeBot):
    def __init__(self, update):
        super().__init__()
        self._update = update
        self.calls = 0

    async def get_updates(self, offset=None, limit=None, timeout=None):
        self.calls += 1
        if self.calls == 1:
            return [self._update]
        raise asyncio.CancelledError()


class PollingLoopTest(unittest.IsolatedAsyncioTestCase):
    async def test_polling_processes_update_then_stops_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            dp = build_dispatcher(
                Settings(bot_token="x"), Storage(Path(tmp) / "p.db")
            )
            bot = PollFakeBot(make_update("/start"))
            with self.assertRaises(asyncio.CancelledError):
                await main_module._polling_loop(bot, dp)  # type: ignore[arg-type]
            await asyncio.sleep(0.05)  # تسک پردازش پیام کامل شود
            self.assertTrue(any("خوش آمدید" in m["text"] for m in bot.sent))


if __name__ == "__main__":
    unittest.main()
