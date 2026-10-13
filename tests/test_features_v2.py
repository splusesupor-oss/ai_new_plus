# -*- coding: utf-8 -*-
"""آزمون قابلیت‌های مرحله دوم: تحویل، اعضا، مسدودی، اطلاع‌رسانی، نوع سفارش.

همه با بات جعلی و دیتابیس موقت؛ بدون پیام یا پرداخت واقعی.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import texts
import video_orders as vo
from config import Settings
from handlers import build_dispatcher
from storage import Storage
from test_handlers import FakeBot, make_update
from test_video_orders import make_callback, make_photo_update, make_video_update

SETTINGS = Settings(
    bot_token="test-token-not-real",
    admin_chat_id="999",
    admin_username="osine2",
    payment_card_number="1111222233334444",
    payment_card_holder="صاحب کارت تست",
    payment_guide_image="/nonexistent/guide.jpg",
)
ADMIN = dict(user_id=999, chat_id=999)
LONG_TEXT = "این متن نمونه برای سفارش ساخت ویدیو است و برای عبور از حداقل طول، بیش از صد کاراکتر دارد تا معتبر باشد."


class FeaturesTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self._tmp.name) / "f.db")
        self.dp = build_dispatcher(SETTINGS, self.storage)
        self.bot = FakeBot()
        self._uid = 100

    def tearDown(self):
        self._tmp.cleanup()

    async def _send(self, update):
        self._uid += 1
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

    def _pending_order(self, user_key="456", chat_id="123"):
        self.storage.get_or_create_user(
            user_key, chat_id=chat_id, username="buyer", display_name="خریدار تست"
        )
        order = self.storage.create_or_get_draft(user_key)
        self.storage.set_order_content(order.id, user_key, "text", LONG_TEXT)
        self.storage.set_order_model(order.id, user_key, "model fox")
        self.storage.set_order_duration(order.id, user_key, 20, 60_000)
        self.storage.request_receipt(order.id, user_key)
        assert self.storage.attach_receipt(order.id, user_key, "receipt-file-1")
        return self.storage.get_order(order.id)

    async def test_members_admin_only_with_details(self):
        u1 = make_update("/start", user_id=456, chat_id=123)
        u1.message.from_user.username = "ali"
        await self._send(u1)
        await self._send(make_update("/start", user_id=777, chat_id=777))
        # کاربر عادی حق ندارد
        await self._send(make_update(vo.ADMIN_MEMBERS_COMMAND, user_id=456, chat_id=123))
        self.assertIn("فقط برای مدیر", self.bot.sent[-1]["text"])
        # مدیر می‌بیند
        before = len(self.bot.sent)
        await self._send(make_update(vo.ADMIN_MEMBERS_COMMAND, **ADMIN))
        joined = "\n".join(m["text"] for m in self.bot.sent[before:])
        self.assertIn("تعداد کل: 3", joined)  # دو کاربر + مدیر (که خودش قوانین را تأیید کرده)
        self.assertIn("@ali", joined)
        code = self.storage.get_user("456").code
        self.assertIn(code, joined)

    async def test_block_and_unblock_user(self):
        await self._send(make_update("/start", user_id=456, chat_id=123))
        code = self.storage.get_user("456").code
        await self._send(make_update(f"{code} مسدود", **ADMIN))
        self.assertTrue(self.storage.get_user("456").is_blocked)
        # هیچ قابلیتی برای مسدود کار نمی‌کند
        await self._send(make_update("/start", user_id=456, chat_id=123))
        self.assertEqual(self.bot.sent[-1]["text"], vo.BLOCKED_TEXT)
        await self._send(make_update(texts.BTN_CREATE_VIDEO, user_id=456, chat_id=123))
        self.assertEqual(self.bot.sent[-1]["text"], vo.BLOCKED_TEXT)
        await self._send(make_callback("vt:text", user_id=456, chat_id=123))
        self.assertTrue(any("مسدود" in (a["text"] or "") for a in self.bot.callback_answers))
        # رفع مسدودیت و بازگشت به حالت عادی
        await self._send(make_update(f"{code} رفع مسدودیت", **ADMIN))
        self.assertFalse(self.storage.get_user("456").is_blocked)
        await self._send(make_update("/start", user_id=456, chat_id=123))
        self.assertEqual(self.bot.sent[-1]["text"], texts.WELCOME_TEXT)

    async def test_order_type_text_min_length(self):
        await self._send(make_update(texts.BTN_CREATE_VIDEO, user_id=456, chat_id=123))
        await self._send(make_callback("vt:text", user_id=456, chat_id=123))
        await self._send(make_update("متن کوتاه", user_id=456, chat_id=123))
        self.assertIn("متن کوتاه است", self.bot.sent[-1]["text"])
        order = self.storage.get_active_order("456")
        self.assertIsNone(order.request_text)
        await self._send(make_update(LONG_TEXT, user_id=456, chat_id=123))
        order = self.storage.get_active_order("456")
        self.assertEqual(order.order_type, "text")
        self.assertEqual(order.request_text, LONG_TEXT)
        self.assertIn("مدل ویدیوساز را انتخاب کنید", self.bot.sent[-1]["text"])

    async def test_order_type_photo_requires_caption(self):
        await self._send(make_update(texts.BTN_CREATE_VIDEO, user_id=456, chat_id=123))
        await self._send(make_callback("vt:photo", user_id=456, chat_id=123))
        photo = make_photo_update(file_id="order-photo-1", user_id=456, chat_id=123)
        await self._send(photo)
        self.assertIn("متن توضیحی داشته باشد", self.bot.sent[-1]["text"])
        photo2 = make_photo_update(file_id="order-photo-1", user_id=456, chat_id=123)
        photo2.message.caption = "عکس یک روباه در جنگل، غروب"
        await self._send(photo2)
        order = self.storage.get_active_order("456")
        self.assertEqual(order.order_type, "photo")
        self.assertEqual(order.request_photo_file_id, "order-photo-1")
        self.assertEqual(order.request_text, "عکس یک روباه در جنگل، غروب")

    async def test_admin_receipt_message_has_bold_full_details(self):
        order = self._pending_order()
        # رسید از مسیر واقعی کاربر می‌آید تا پیام مدیر ساخته شود
        self.storage.get_or_create_user("888", chat_id="888", username="buyer2")
        order2 = self.storage.create_or_get_draft("888")
        self.storage.set_order_content(order2.id, "888", "text", LONG_TEXT)
        self.storage.set_order_model(order2.id, "888", "model plus")
        self.storage.set_order_duration(order2.id, "888", 10, 35_000)
        self.storage.request_receipt(order2.id, "888")
        photo = make_photo_update(user_id=888, chat_id=888)
        photo.message.from_user.username = "buyer2"
        await self._send(photo)
        self.assertTrue(self.bot.photos)
        caption = self.bot.photos[0]["caption"]
        self.assertIn("<b>", caption)
        for needle in ("نوع سفارش", "شناسه شش‌رقمی", "مدل انتخابی", "مبلغ"):
            self.assertIn(needle, caption)
        # جزئیات فقط یک بار و همراه خود رسید آمده؛ پیام متنی جداگانه‌ای برای مدیر نیست
        self.assertIn(LONG_TEXT, caption)
        self.assertIn("@buyer2", caption)
        admin_texts = [m for m in self.bot.sent if str(m["chat_id"]) == "999"]
        self.assertEqual(admin_texts, [])

    async def test_delivery_after_approval(self):
        order = self._pending_order()
        await self._send(make_callback(f"va:{order.id}", **ADMIN))
        self.assertEqual(self.storage.get_order(order.id).status, "payment_approved")
        # مدیر پیام درخواست تحویل با دکمه «ارسال ویدیو» گرفته است
        deliver_msgs = [
            m for m in self.bot.sent
            if str(m["chat_id"]) == "999" and m.get("reply_markup") is not None
            and any(
                b.callback_data == f"vdl:{order.id}"
                for row in m["reply_markup"].inline_keyboard
                for b in row
            )
        ]
        self.assertTrue(deliver_msgs)
        await self._send(make_callback(f"vdl:{order.id}", **ADMIN))
        await self._send(make_video_update(file_id="final-video-1", **ADMIN))
        sent_video = [v for v in self.bot.videos if str(v["chat_id"]) == "123"]
        self.assertTrue(sent_video)
        self.assertEqual(sent_video[0]["video"], "final-video-1")
        saved = self.storage.get_order(order.id)
        self.assertEqual(saved.status, "completed")
        self.assertEqual(saved.delivered_video_file_id, "final-video-1")

    async def test_broadcast_preview_confirm_and_cancel(self):
        self.storage.get_or_create_user("456", chat_id="123")
        self.storage.get_or_create_user("777", chat_id="777")
        blocked = self.storage.get_or_create_user("555", chat_id="555")
        self.storage.set_blocked_by_code(blocked.code, True)
        base = len(self.bot.sent)
        await self._send(make_update(vo.ADMIN_BROADCAST_COMMAND, **ADMIN))
        await self._send(make_update("سلام **اطلاعیه مهم** برای همه", **ADMIN))
        preview = self.bot.sent[-1]
        self.assertIn("<b>اطلاعیه مهم</b>", preview["text"])
        self.assertEqual(preview.get("parse_mode"), "HTML")
        # لغو: چیزی برای اعضا نمی‌رود
        await self._send(make_callback("vbc:cancel", **ADMIN))
        member_msgs = [m for m in self.bot.sent[base:] if str(m["chat_id"]) in {"123", "777", "555"}]
        self.assertEqual(member_msgs, [])
        # تأیید: فقط اعضای غیرمسدود می‌گیرند
        await self._send(make_update(vo.ADMIN_BROADCAST_COMMAND, **ADMIN))
        await self._send(make_update("سلام **اطلاعیه مهم** برای همه", **ADMIN))
        await self._send(make_callback("vbc:confirm", **ADMIN))
        got = {str(m["chat_id"]) for m in self.bot.sent if "اطلاعیه مهم" in m["text"]}
        self.assertIn("123", got)
        self.assertIn("777", got)
        self.assertNotIn("555", got)  # مسدودها نمی‌گیرند


if __name__ == "__main__":
    unittest.main()
