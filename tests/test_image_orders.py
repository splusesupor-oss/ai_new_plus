# -*- coding: utf-8 -*-
"""آزمون ساخت تصویر و اعتبار رایگان روزانه — بدون شبکه و پیام واقعی."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import image_orders as io
import texts
import video_orders as vo
from config import Settings
from handlers import build_dispatcher
from keyboards import build_image_model_keyboard, build_image_mode_keyboard, inline_to_dict
from storage import Storage
from test_handlers import FakeBot, make_update
from test_video_orders import make_callback, make_photo_update

SETTINGS = Settings(
    bot_token="test-token-not-real",
    admin_chat_id="999",
    payment_card_number="1111222233334444",
    payment_card_holder="صاحب کارت تست",
    payment_guide_image="/nonexistent/guide.jpg",
)
ADMIN = dict(user_id=999, chat_id=999)


class ImageKeyboardsTest(unittest.TestCase):
    def test_mode_and_model_buttons_exact(self):
        modes = [
            b["text"]
            for row in inline_to_dict(build_image_mode_keyboard())["inline_keyboard"]
            for b in row
        ]
        self.assertEqual(modes, ["تولید تصویر", "ویرایش تصویر", "تغییر چهره"])
        models = [
            b["text"]
            for row in inline_to_dict(build_image_model_keyboard())["inline_keyboard"]
            for b in row
        ]
        self.assertEqual(models, ["GPT 6", "flash pro 3", "nano banana pro", "fox plus 6"])


class ImageFlowTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self._tmp.name) / "img.db")
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

    async def _start_image(self, uid=1, user_id=456, chat_id=123):
        await self._send(
            make_update(texts.BTN_CREATE_IMAGE, update_id=uid, user_id=user_id, chat_id=chat_id)
        )

    async def test_intro_image_and_bold_text(self):
        await self._start_image()
        # عکس و متن و دکمه‌ها باید در یک پیام واحد باشند، نه دو پیام جدا
        self.assertEqual(len(self.bot.photos), 1)
        self.assertEqual(self.bot.sent, [])
        intro = self.bot.photos[0]
        self.assertTrue(str(intro["photo"]).endswith("image_hero.jpg"))
        self.assertIn("<b>", intro["caption"])
        self.assertIn("🖼 سفارش تصویر با هوش مصنوعی روباه", intro["caption"])
        self.assertIn("نحوه تولید را انتخاب کنید", intro["caption"])
        modes = [
            b.text
            for row in intro["reply_markup"].inline_keyboard
            for b in row
        ]
        self.assertEqual(modes, ["تولید تصویر", "ویرایش تصویر", "تغییر چهره"])

    async def test_generation_flow_deducts_10_and_notifies_admin(self):
        await self._start_image()
        await self._send(make_callback("it:gen", update_id=2))
        await self._send(make_callback("im:0", update_id=3))
        await self._send(make_update("یک روباه نارنجی در جنگل مه‌آلود", update_id=4))
        order = self.storage.list_user_orders("456")[0]
        self.assertEqual(order.service, "image")
        self.assertEqual(order.image_mode, "gen")
        self.assertEqual(order.model, "GPT 6")
        self.assertEqual(order.status, "pending_review")
        self.assertEqual(self.storage.ensure_daily_credit("456"), 40)
        # سفارش بدون پرداخت برای مدیر رفته است
        admin_msg = [m for m in self.bot.sent if str(m["chat_id"]) == "999"]
        self.assertTrue(admin_msg)
        self.assertIn("روباه نارنجی", admin_msg[-1]["text"])
        self.assertIn("تولید تصویر", admin_msg[-1]["text"])

    async def test_admin_as_user_can_finish_generation_prompt(self):
        # رگرسیون: صاحب ربات (مدیر) هم وقتی «ساخت تصویر» را شروع می‌کند باید
        # بتواند پرامپت بفرستد و سفارشش ثبت شود (قبلاً این مرحله گیر می‌کرد).
        await self._start_image(uid=10, **ADMIN)
        await self._send(make_callback("it:gen", update_id=11, **ADMIN))
        await self._send(make_callback("im:3", update_id=12, **ADMIN))
        await self._send(make_update("روباهی که برای مدیر نقاشی می‌کشد", update_id=13, **ADMIN))
        order = self.storage.list_user_orders("999")[0]
        self.assertEqual(order.service, "image")
        self.assertEqual(order.model, "fox plus 6")
        self.assertEqual(order.request_text, "روباهی که برای مدیر نقاشی می‌کشد")
        self.assertEqual(self.storage.ensure_daily_credit("999"), 40)

    async def test_edit_flow_photo_with_caption_and_admin_photo(self):
        await self._start_image()
        await self._send(make_callback("it:edit", update_id=2))
        await self._send(make_callback("im:2", update_id=3))
        photo = make_photo_update(file_id="user-photo-1")
        await self._send(photo)
        self.assertIn("متن توضیحی داشته باشد", self.bot.sent[-1]["text"])
        photo2 = make_photo_update(file_id="user-photo-1")
        photo2.message.caption = "پس‌زمینه را غروب کن"
        await self._send(photo2)
        order = self.storage.list_user_orders("456")[0]
        self.assertEqual(order.image_mode, "edit")
        self.assertEqual(order.model, "nano banana pro")
        self.assertEqual(order.request_photo_file_id, "user-photo-1")
        self.assertEqual(self.storage.ensure_daily_credit("456"), 40)
        self.assertTrue(any(str(p["chat_id"]) == "999" for p in self.bot.photos))

    async def test_no_credit_after_five_orders(self):
        self.storage.get_or_create_user("456", chat_id="123")
        for i in range(5):
            order = self.storage.create_image_order("456", "gen", "GPT 6", f"پرامپت {i}")
            self.assertIsNotNone(order)
        self.assertEqual(self.storage.ensure_daily_credit("456"), 0)
        self.assertIsNone(self.storage.create_image_order("456", "gen", "GPT 6", "ششمی"))
        # از مسیر ربات هم پیام اتمام اعتبار می‌آید
        await self._start_image()
        await self._send(make_callback("it:face", update_id=2))
        await self._send(make_callback("im:1", update_id=3))
        photo = make_photo_update(file_id="face-1")
        photo.message.caption = "چهره را جوان‌تر کن"
        await self._send(photo)
        self.assertIn("اعتبار رایگان امروزتان تمام شده است", self.bot.sent[-1]["text"])

    async def test_free_credit_button_and_midnight_reset(self):
        await self._send(make_update(texts.BTN_FREE_CREDIT, user_id=456, chat_id=123))
        self.assertTrue(self.bot.photos)
        caption = self.bot.photos[-1]["caption"]
        self.assertIn("شما 50 اعتبار رایگان برای ساخت 5 عکس دریافت کردید", caption)
        # دیروز اعتبار تمام شده بود؛ امروز (تهران) خودکار ۵۰ می‌شود
        self.storage.create_image_order("456", "gen", "GPT 6", "x")
        with self.storage._connect() as conn:
            conn.execute(
                "UPDATE users SET credit_balance=0, credit_date='2000-01-01' WHERE user_key='456'"
            )
        self.assertEqual(self.storage.ensure_daily_credit("456"), 50)

    async def test_admin_delivers_and_reject_refunds(self):
        self.storage.get_or_create_user("456", chat_id="123")
        order = self.storage.create_image_order("456", "gen", "fox plus 6", "یک شهر آینده‌نگر")
        self.assertEqual(self.storage.ensure_daily_credit("456"), 40)
        # تحویل: مدیر دکمه را می‌زند و عکس نهایی را می‌فرستد
        await self._send(make_callback(f"idl:{order.id}", **ADMIN))
        final = make_photo_update(file_id="final-img-1", **ADMIN)
        await self._send(final)
        saved = self.storage.get_order(order.id)
        self.assertEqual(saved.status, "completed")
        self.assertEqual(saved.delivered_file_id, "final-img-1")
        self.assertTrue(any(str(p["chat_id"]) == "123" for p in self.bot.photos))
        # رد سفارش دوم: اعتبار برمی‌گردد
        order2 = self.storage.create_image_order("456", "edit", "GPT 6", "ویرایش")
        self.assertEqual(self.storage.ensure_daily_credit("456"), 30)
        await self._send(make_callback(f"irj:{order2.id}", **ADMIN))
        self.assertEqual(self.storage.get_order(order2.id).status, "rejected")
        self.assertEqual(self.storage.ensure_daily_credit("456"), 40)
        # به کاربر صریح گفته شده سفارش «رد شد»
        user_msgs = [m["text"] for m in self.bot.sent if str(m["chat_id"]) == "123"]
        self.assertTrue(any("رد شد" in t for t in user_msgs))

    async def test_image_order_status_labels_waiting_photo_and_rejected(self):
        self.storage.get_or_create_user("456", chat_id="123")
        order = self.storage.create_image_order("456", "gen", "GPT 6", "یک منظره کوهستانی")
        user = self.storage.get_user("456")
        # مدیر هم وضعیت را «در انتظار ارسال عکس» می‌بیند، نه بررسی پرداخت
        admin_html = io.image_admin_html(order, user)
        self.assertIn("در انتظار ارسال عکس", admin_html)
        self.assertNotIn("در انتظار پرداخت", admin_html)
        self.assertNotIn("بررسی پرداخت", admin_html)
        # و کاربر در «سفارش‌های من»
        await self._send(make_update(texts.BTN_MY_ORDERS, update_id=30))
        mine = self.bot.sent[-1]["text"]
        self.assertIn("وضعیت: در انتظار ارسال عکس", mine)
        self.assertNotIn("در انتظار پرداخت", mine)
        # بعد از رد مدیر: همه‌جا «رد شد»
        await self._send(make_callback(f"irj:{order.id}", update_id=31, **ADMIN))
        await self._send(make_update(texts.BTN_MY_ORDERS, update_id=32))
        mine = self.bot.sent[-1]["text"]
        self.assertIn("وضعیت: رد شد", mine)
        rejected_html = io.image_admin_html(self.storage.get_order(order.id), user)
        self.assertIn("رد شد", rejected_html)

    async def test_rejected_image_order_is_final_and_cannot_be_delivered(self):
        self.storage.get_or_create_user("456", chat_id="123")
        order = self.storage.create_image_order("456", "gen", "GPT 6", "یک شهر آینده‌نگر")
        # مدیر اول تحویل را شروع می‌کند، بعد پشیمان می‌شود و رد می‌کند
        await self._send(make_callback(f"idl:{order.id}", update_id=40, **ADMIN))
        self.assertEqual(self.storage.get_order(order.id).status, "processing")
        await self._send(make_callback(f"irj:{order.id}", update_id=41, **ADMIN))
        self.assertEqual(self.storage.get_order(order.id).status, "rejected")
        self.assertIsNone(self.storage.get_flow_state("999"))  # حالت تحویل پاک شد
        photos_before = len([p for p in self.bot.photos if str(p["chat_id"]) == "123"])
        # ارسال دیرهنگام عکس نباید سفارش ردشده را تکمیل یا برای کاربر بفرستد
        await self._send(make_photo_update(file_id="late-final-img", update_id=42, **ADMIN))
        self.assertEqual(self.storage.get_order(order.id).status, "rejected")
        self.assertIsNone(self.storage.get_order(order.id).delivered_file_id)
        self.assertEqual(
            len([p for p in self.bot.photos if str(p["chat_id"]) == "123"]), photos_before
        )
        saved = self.storage.complete_image_delivery(order.id, "late-final-img")
        self.assertEqual(saved.status, "rejected")

    async def test_pending_list_and_payment_buttons_do_not_touch_image_orders(self):
        self.storage.get_or_create_user("456", chat_id="123")
        order = self.storage.create_image_order("456", "edit", "GPT 6", "ویرایش عکس")
        await self._send(make_update(vo.ADMIN_PENDING_COMMAND, update_id=50, **ADMIN))
        image_msgs = [
            m for m in self.bot.sent
            if str(m["chat_id"]) == "999" and m.get("reply_markup") is not None
        ]
        self.assertTrue(image_msgs)
        callbacks = {
            b.callback_data
            for m in image_msgs
            for row in m["reply_markup"].inline_keyboard
            for b in row
        }
        # فهرست انتظار برای عکس، دکمه‌های خودش را می‌دهد نه تأیید/رد پرداخت
        self.assertIn(f"idl:{order.id}", callbacks)
        self.assertIn(f"irj:{order.id}", callbacks)
        self.assertNotIn(f"va:{order.id}", callbacks)
        self.assertNotIn(f"vrj:{order.id}", callbacks)
        # و اگر دکمه پرداخت ویدیو اشتباهی روی سفارش عکس زده شود، اثری ندارد
        await self._send(make_callback(f"vrj:{order.id}", update_id=51, **ADMIN))
        self.assertEqual(self.storage.get_order(order.id).status, "pending_review")
        self.assertEqual(self.storage.ensure_daily_credit("456"), 40)


if __name__ == "__main__":
    unittest.main()
