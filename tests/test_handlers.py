# -*- coding: utf-8 -*-
"""آزمون یکپارچه هندلرها با بات جعلی — بدون شبکه و بدون ارسال پیام واقعی.

پیام‌ها با همان مدل‌های واقعی کتابخانه aiosplus ساخته می‌شوند و از
مسیر واقعی Dispatcher عبور می‌کنند؛ فقط لایه ارسال (بات) جعلی است.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import texts
from aiosplus.types import Chat, Message, Update, User
from config import Settings
from handlers import build_dispatcher
from keyboards import keyboard_to_dict

SETTINGS = Settings(bot_token="test-token-not-real")


class FakeBot:
    """به‌جای Bot واقعی؛ فقط فراخوانی‌های send_message را ثبت می‌کند."""

    _me = None  # فیلتر Command هنگام وجود @mention به آن سر می‌زند

    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None, **kwargs):
        self.sent.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})
        return None


def make_update(text, update_id=1):
    message = Message(
        message_id=update_id,
        date=1700000000,
        chat=Chat(id=123, type="private"),
        from_user=User(id=456, is_bot=False, first_name="تست"),
        text=text,
    )
    return Update(update_id=update_id, message=message)


class HandlersTest(unittest.IsolatedAsyncioTestCase):
    async def _dispatch(self, text):
        bot = FakeBot()
        dp = build_dispatcher(SETTINGS)
        handled = await dp.feed_update(bot, make_update(text))  # type: ignore[arg-type]
        self.assertTrue(handled)
        self.assertEqual(len(bot.sent), 1)
        return bot.sent[0]

    async def test_start_sends_welcome_with_reply_keyboard(self):
        sent = await self._dispatch("/start")
        self.assertEqual(sent["text"], texts.WELCOME_TEXT)
        data = keyboard_to_dict(sent["reply_markup"])
        rows = [[b["text"] for b in row] for row in data["keyboard"]]
        self.assertEqual(rows[0], ["ساخت تصویر", "ساخت ویدیو"])
        self.assertEqual(rows[3], ["گروه روباه", "کانال روباه"])

    async def test_menu_command_and_persian_menu(self):
        for text in ("/menu", "منو"):
            with self.subTest(text=text):
                sent = await self._dispatch(text)
                self.assertEqual(sent["text"], texts.WELCOME_TEXT)

    async def test_buttons_via_dispatcher(self):
        cases = {
            texts.BTN_CREATE_IMAGE: "بخش ساخت تصویر به‌زودی فعال می‌شود.",
            texts.BTN_CREATE_VIDEO: "بخش ساخت ویدیو به‌زودی فعال می‌شود.",
            texts.BTN_MY_ORDERS: "هنوز راه‌اندازی نشده است",
            texts.BTN_SAMPLES: "به‌زودی اضافه می‌شوند",
        }
        for btn, expected in cases.items():
            with self.subTest(btn=btn):
                sent = await self._dispatch(btn)
                self.assertIn(expected, sent["text"])
                self.assertIsNotNone(sent["reply_markup"])  # کیبورد اصلی باقی می‌ماند

    async def test_unknown_text_gets_fallback_with_keyboard(self):
        sent = await self._dispatch("متن ناشناخته")
        self.assertEqual(sent["text"], texts.UNKNOWN_TEXT)
        self.assertIsNotNone(sent["reply_markup"])


if __name__ == "__main__":
    unittest.main()
