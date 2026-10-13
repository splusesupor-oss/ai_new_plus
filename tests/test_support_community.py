# -*- coding: utf-8 -*-
"""آزمون پشتیبانی (ریپلای مدیر)، گروه، کانال و نمونه‌ها — بدون شبکه."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import support as sup
import texts
from aiosplus.types import Chat, Message, Update, User
from config import Settings
from handlers import build_dispatcher
from keyboards import inline_to_dict
from storage import Storage
from test_handlers import FakeBot, make_update

SETTINGS = Settings(
    bot_token="test-token-not-real",
    admin_chat_id="999",
    payment_card_number="1111222233334444",
    payment_card_holder="صاحب کارت تست",
    payment_guide_image="/nonexistent/guide.jpg",
)
ADMIN = dict(user_id=999, chat_id=999)


def make_reply_update(text, reply_text, reply_message_id, update_id=90, user_id=999, chat_id=999):
    original = Message(
        message_id=reply_message_id,
        date=1700000000,
        chat=Chat(id=chat_id, type="private"),
        from_user=User(id=111, is_bot=True, first_name="ربات"),
        text=reply_text,
    )
    message = Message(
        message_id=update_id,
        date=1700000000,
        chat=Chat(id=chat_id, type="private"),
        from_user=User(id=user_id, is_bot=False, first_name="مدیر"),
        text=text,
        reply_to_message=original,
    )
    return Update(update_id=update_id, message=message)


class SupportCommunityTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self._tmp.name) / "sup.db")
        self.dp = build_dispatcher(SETTINGS, self.storage)
        self.bot = FakeBot()

    def tearDown(self):
        self._tmp.cleanup()

    async def _send(self, update):
        # دروازه قوانین در test_rules_gate.py سنجیده می‌شود؛ اینجا فرستنده
        # از قبل قوانین را تأیید کرده فرض می‌شود.
        sender = None
        chat_id = None
        if update.message is not None:
            sender = update.message.from_user
            chat_id = update.message.chat.id
        elif update.callback_query is not None:
            sender = update.callback_query.from_user
            chat_id = update.callback_query.message.chat.id if update.callback_query.message else None
        if sender is not None:
            self.storage.get_or_create_user(str(sender.id), chat_id=str(chat_id))
            self.storage.set_rules_accepted(str(sender.id), True)
        handled = await self.dp.feed_update(self.bot, update)  # type: ignore[arg-type]
        self.assertTrue(handled)

    async def test_support_prompt_exact_text(self):
        await self._send(make_update(texts.BTN_SUPPORT, update_id=1))
        self.assertEqual(self.bot.sent[-1]["text"], "پیام خودتون رو برای پشتیبانی بنویسید")

    async def test_support_message_to_admin_and_admin_reply_to_user(self):
        await self._send(make_update(texts.BTN_SUPPORT, update_id=1))
        await self._send(make_update("سلام، سفارش من هنوز نرسیده", update_id=2))
        admin_msgs = [m for m in self.bot.sent if str(m["chat_id"]) == "999"]
        self.assertTrue(admin_msgs)
        admin_text = admin_msgs[-1]["text"]
        self.assertIn("سلام، سفارش من هنوز نرسیده", admin_text)
        code = self.storage.get_user("456").code
        self.assertIn(code, admin_text)  # مشخصات کاربر برای مدیر آمده است
        self.assertIn("شناسه سروش‌پلاس:</b> 456", admin_text)
        # کاربر تأیید گرفته و تیکت با شناسه پیام مدیر ذخیره شده است
        self.assertTrue(any("برای پشتیبانی ارسال شد" in m["text"] for m in self.bot.sent if str(m["chat_id"]) == "123"))
        ticket = self.storage.get_support_message(1)
        self.assertIsNotNone(ticket)
        self.assertIsNotNone(ticket.admin_message_id)

        # مدیر روی همان پیام ریپلای می‌کند → جواب برای همان کاربر می‌رود
        await self._send(
            make_reply_update(
                "سلام، امروز ارسال می‌شود",
                reply_text=admin_text,
                reply_message_id=int(ticket.admin_message_id),
            )
        )
        user_msgs = [m for m in self.bot.sent if str(m["chat_id"]) == "123"]
        self.assertIn("پاسخ پشتیبانی", user_msgs[-1]["text"])
        self.assertIn("سلام، امروز ارسال می‌شود", user_msgs[-1]["text"])

    async def test_support_reply_fallback_by_ref_code(self):
        # حتی اگر شناسه پیام مدیر در دسترس نباشد، کد SUP داخل متن کافی است
        self.storage.get_or_create_user("456", chat_id="123")
        ticket = self.storage.create_support_message("456", "123", "999")
        await self._send(
            make_reply_update(
                "پاسخ با کد پیگیری",
                reply_text=f"پیام قبلی {sup.support_ref(ticket.id)}",
                reply_message_id=424242,
            )
        )
        user_msgs = [m for m in self.bot.sent if str(m["chat_id"]) == "123"]
        self.assertIn("پاسخ با کد پیگیری", user_msgs[-1]["text"])

    async def test_support_reply_from_non_admin_goes_nowhere(self):
        self.storage.get_or_create_user("456", chat_id="123")
        ticket = self.storage.create_support_message("456", "123", "999")
        await self._send(
            make_reply_update(
                "من مدیر نیستم",
                reply_text=f"{sup.support_ref(ticket.id)}",
                reply_message_id=1,
                user_id=777,
                chat_id=777,
            )
        )
        self.assertFalse(any("من مدیر نیستم" in m["text"] for m in self.bot.sent))

    async def test_samples_exact_text(self):
        await self._send(make_update(texts.BTN_SAMPLES, update_id=1))
        self.assertEqual(self.bot.sent[-1]["text"], "به زودی ...")

    async def test_group_photo_and_url_button(self):
        await self._send(make_update(texts.BTN_GROUP, update_id=1))
        # گروه باید فقط یک پیام واحد باشد: عکس + کپشن + دکمه، بدون پیام متنی جدا
        self.assertEqual(self.bot.sent, [])
        self.assertEqual(len(self.bot.photos), 1)
        photo = self.bot.photos[-1]
        self.assertTrue(str(photo["photo"]).endswith("fox_group.jpg"))
        self.assertEqual(photo["caption"], texts.GROUP_CAPTION)
        data = inline_to_dict(photo["reply_markup"])
        button = data["inline_keyboard"][0][0]
        self.assertEqual(button["url"], "https://splus.ir/joingroup/AI_hfuzaN9GGKPWF0MsDJg")

    async def test_channel_text_and_username_button(self):
        await self._send(make_update(texts.BTN_CHANNEL, update_id=1))
        sent = self.bot.sent[-1]
        self.assertEqual(sent["text"], "🦑 : کانال اصلی انجمن روباه")
        data = inline_to_dict(sent["reply_markup"])
        button = data["inline_keyboard"][0][0]
        self.assertEqual(button["text"], "@ai_fox")
        self.assertEqual(button["url"], "https://splus.ir/ai_fox")


if __name__ == "__main__":
    unittest.main()
