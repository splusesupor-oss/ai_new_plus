# -*- coding: utf-8 -*-
"""آزمون یکپارچه هندلرهای پایه با بات جعلی — بدون شبکه و بدون پیام واقعی.

پیام‌ها با همان مدل‌های واقعی کتابخانه aiosplus ساخته می‌شوند و از
مسیر واقعی Dispatcher عبور می‌کنند؛ فقط لایه ارسال (بات) جعلی است.
فرایند کامل سفارش ویدیو در test_video_orders.py پوشش داده شده است.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import texts
from aiosplus.types import Chat, Message, Update, User
from config import Settings
from handlers import build_dispatcher
from keyboards import keyboard_to_dict
from storage import Storage

SETTINGS = Settings(bot_token="test-token-not-real")


class FakeBot:
    """به‌جای Bot واقعی؛ همه فراخوانی‌های ارسال را فقط ثبت می‌کند."""

    _me = None  # فیلتر Command هنگام وجود @mention به آن سر می‌زند

    def __init__(self):
        self.sent = []
        self.photos = []
        self.videos = []
        self.callback_answers = []

    async def send_message(self, chat_id, text, reply_markup=None, **kwargs):
        self.sent.append(
            {"chat_id": chat_id, "text": text, "reply_markup": reply_markup, **kwargs}
        )
        return None

    async def send_photo(self, chat_id, photo, caption=None, reply_markup=None, **kwargs):
        self.photos.append(
            {"chat_id": chat_id, "photo": photo, "caption": caption, "reply_markup": reply_markup}
        )
        return None

    async def send_video(self, chat_id, video, caption=None, reply_markup=None, **kwargs):
        self.videos.append({"chat_id": chat_id, "video": video, "caption": caption})
        return None

    async def answer_callback_query(self, callback_query_id, text=None, show_alert=None, **kwargs):
        self.callback_answers.append({"id": callback_query_id, "text": text})
        return True


def make_update(text, update_id=1, user_id=456, chat_id=123):
    message = Message(
        message_id=update_id,
        date=1700000000,
        chat=Chat(id=chat_id, type="private"),
        from_user=User(id=user_id, is_bot=False, first_name="تست"),
        text=text,
    )
    return Update(update_id=update_id, message=message)


class HandlersTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self._tmp.name) / "test.db")

    def tearDown(self):
        self._tmp.cleanup()

    async def _dispatch(self, text, user_id=456, chat_id=123):
        bot = FakeBot()
        dp = build_dispatcher(SETTINGS, self.storage)
        handled = await dp.feed_update(bot, make_update(text, user_id=user_id, chat_id=chat_id))  # type: ignore[arg-type]
        self.assertTrue(handled)
        return bot

    async def test_start_sends_welcome_with_reply_keyboard(self):
        bot = await self._dispatch("/start")
        self.assertEqual(len(bot.sent), 1)
        sent = bot.sent[0]
        self.assertEqual(sent["text"], texts.WELCOME_TEXT)
        data = keyboard_to_dict(sent["reply_markup"])
        rows = [[b["text"] for b in row] for row in data["keyboard"]]
        self.assertEqual(rows[0], ["ساخت تصویر", "ساخت ویدیو"])
        self.assertEqual(rows[3], ["گروه روباه", "کانال روباه"])

    async def test_menu_command_and_persian_menu(self):
        for text in ("/menu", "منو"):
            with self.subTest(text=text):
                bot = await self._dispatch(text)
                self.assertEqual(bot.sent[0]["text"], texts.WELCOME_TEXT)

    async def test_static_buttons_via_dispatcher(self):
        cases = {
            texts.BTN_SAMPLES: "به‌زودی اضافه می‌شوند",
        }
        for btn, expected in cases.items():
            with self.subTest(btn=btn):
                bot = await self._dispatch(btn)
                self.assertIn(expected, bot.sent[0]["text"])
                self.assertIsNotNone(bot.sent[0]["reply_markup"])  # کیبورد اصلی باقی می‌ماند

    async def test_unknown_text_gets_fallback_with_keyboard(self):
        bot = await self._dispatch("متن ناشناخته")
        self.assertEqual(bot.sent[0]["text"], texts.UNKNOWN_TEXT)
        self.assertIsNotNone(bot.sent[0]["reply_markup"])


if __name__ == "__main__":
    unittest.main()
