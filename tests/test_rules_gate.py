# -*- coding: utf-8 -*-
"""آزمون دروازه قوانین: تا تأیید نشود، هیچ منو و دکمه‌ای باز نمی‌شود."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import texts
from config import Settings
from handlers import build_dispatcher
from keyboards import inline_to_dict, keyboard_to_dict
from storage import Storage
from test_handlers import FakeBot, make_update
from test_video_orders import make_callback

SETTINGS = Settings(
    bot_token="test-token-not-real",
    admin_chat_id="999",
    payment_card_number="1111222233334444",
    payment_card_holder="صاحب کارت تست",
    payment_guide_image="/nonexistent/guide.jpg",
)


class RulesGateTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "rules.db"
        self.storage = Storage(self.db)
        self.dp = build_dispatcher(SETTINGS, self.storage)
        self.bot = FakeBot()

    def tearDown(self):
        self._tmp.cleanup()

    async def _send(self, update):
        handled = await self.dp.feed_update(self.bot, update)  # type: ignore[arg-type]
        self.assertTrue(handled)

    def _assert_rules_photo(self, photo):
        self.assertTrue(str(photo["photo"]).endswith("rules.jpg"))
        self.assertIn("قوانین", photo["caption"])
        data = inline_to_dict(photo["reply_markup"])
        button = data["inline_keyboard"][0][0]
        self.assertEqual(button["text"], "✅ تأیید قوانین")
        self.assertEqual(button["callback_data"], "rules:accept")

    async def test_first_start_rules_photo_and_button_no_menu(self):
        await self._send(make_update("/start", update_id=1))
        self.assertEqual(self.bot.sent, [])  # هیچ پیام منو/خوشامدی نرفته است
        self.assertEqual(len(self.bot.photos), 1)
        self._assert_rules_photo(self.bot.photos[0])
        self.assertFalse(self.storage.has_accepted_rules("456"))

    async def test_no_button_or_menu_opens_before_acceptance(self):
        await self._send(make_update("/start", update_id=1))
        # دکمه منوی اصلی قبل از تأیید کار نمی‌کند؛ فقط قوانین می‌آید
        await self._send(make_update(texts.BTN_CREATE_IMAGE, update_id=2))
        self.assertEqual(len(self.bot.photos), 2)
        self._assert_rules_photo(self.bot.photos[-1])
        self.assertFalse(any("سفارش تصویر" in (m.get("text") or "") for m in self.bot.sent))
        # متن آزاد هم جلو نمی‌رود
        await self._send(make_update("سلام", update_id=3))
        self.assertEqual(len(self.bot.photos), 3)
        # کال‌بک دکمه‌های قدیمی هم قفل است و وضعیتی ساخته نمی‌شود
        await self._send(make_callback("it:gen", update_id=4))
        self.assertIsNone(self.storage.get_flow_state("456"))
        self.assertTrue(any("ابتدا قوانین را تأیید کنید" in (a["text"] or "") for a in self.bot.callback_answers))
        # /menu هم قبل از تأیید منو نمی‌دهد
        await self._send(make_update("/menu", update_id=5))
        self.assertEqual(len(self.bot.photos), 4)
        self.assertFalse(self.storage.has_accepted_rules("456"))

    async def test_accept_rules_opens_menu_and_persists(self):
        await self._send(make_update("/start", update_id=1))
        await self._send(make_callback("rules:accept", update_id=2))
        self.assertTrue(self.storage.has_accepted_rules("456"))
        welcome = self.bot.sent[-1]
        self.assertEqual(welcome["text"], texts.WELCOME_TEXT)
        rows = [[b["text"] for b in row] for row in keyboard_to_dict(welcome["reply_markup"])["keyboard"]]
        self.assertEqual(rows[0], ["ساخت تصویر", "ساخت ویدیو"])
        # تأیید در دیتابیس می‌ماند و با اجرای دوباره ربات از بین نمی‌رود
        reopened = Storage(self.db)
        self.assertTrue(reopened.has_accepted_rules("456"))
        # بعد از تأیید، دکمه‌های منو عادی کار می‌کنند
        await self._send(make_update(texts.BTN_SAMPLES, update_id=3))
        self.assertEqual(self.bot.sent[-1]["text"], "به زودی ...")
        await self._send(make_update("/start", update_id=4))
        self.assertEqual(self.bot.sent[-1]["text"], texts.WELCOME_TEXT)


if __name__ == "__main__":
    unittest.main()
