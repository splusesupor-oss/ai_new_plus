# -*- coding: utf-8 -*-
"""آزمون سیستم سفارش ویدیو — بدون پرداخت واقعی و بدون ارسال پیام واقعی.

پوشش: کد شش‌رقمی، انتخاب مدل/مدت/مبلغ، ضدتکرار، رسید، صف مدیر،
تأیید/رد مدیر، سفارش‌های من، تنظیم ویدیوی دائمی و جدایی کاربران.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import texts
import video_orders as vo
from aiosplus.types import CallbackQuery, Chat, Message, PhotoSize, Update, User, Video
from config import Settings
from handlers import build_dispatcher
from keyboards import (
    build_duration_keyboard,
    build_model_keyboard,
    build_receipt_keyboard,
    inline_to_dict,
)
from storage import Storage
from test_handlers import FakeBot, make_update

TEST_SETTINGS = Settings(
    bot_token="test-token-not-real",
    admin_chat_id="999",
    payment_card_number="1111222233334444",
    payment_card_holder="صاحب کارت تست",
    payment_guide_image="/nonexistent/guide.jpg",  # مسیر ناموجود: مسیر متنی پرداخت تست شود
)


def make_photo_update(file_id="receipt-file-1", user_id=456, chat_id=123, update_id=50):
    message = Message(
        message_id=update_id,
        date=1700000000,
        chat=Chat(id=chat_id, type="private"),
        from_user=User(id=user_id, is_bot=False, first_name="تست"),
        photo=[PhotoSize(file_id=file_id, file_unique_id="u1", width=100, height=100, file_size=10)],
    )
    return Update(update_id=update_id, message=message)


def make_video_update(file_id="default-video-1", user_id=999, chat_id=999, update_id=60):
    message = Message(
        message_id=update_id,
        date=1700000000,
        chat=Chat(id=chat_id, type="private"),
        from_user=User(id=user_id, is_bot=False, first_name="مدیر"),
        video=Video(file_id=file_id, file_unique_id="v1", width=640, height=360, duration=5),
    )
    return Update(update_id=update_id, message=message)


def make_callback(data, user_id=456, chat_id=123, update_id=70):
    message = Message(
        message_id=1,
        date=1700000000,
        chat=Chat(id=chat_id, type="private"),
        from_user=User(id=111, is_bot=True, first_name="ربات"),
        text="پیام ربات",
    )
    callback = CallbackQuery(
        id=f"cb-{update_id}-{data}",
        from_user=User(id=user_id, is_bot=False, first_name="تست"),
        message=message,
        data=data,
    )
    return Update(update_id=update_id, callback_query=callback)


class StorageTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "t.db"
        self.store = Storage(self.db)

    def tearDown(self):
        self._tmp.cleanup()

    def test_six_digit_code_stable_unique_and_persistent(self):
        u1 = self.store.get_or_create_user("1001", chat_id="1001")
        u2 = self.store.get_or_create_user("1002", chat_id="1002")
        self.assertRegex(u1.code, r"^\d{6}$")
        self.assertNotEqual(u1.code, u2.code)
        again = self.store.get_or_create_user("1001", chat_id="1001")
        self.assertEqual(again.code, u1.code)  # با /start مجدد عوض نمی‌شود
        reopened = Storage(self.db)  # ری‌استارت ربات
        self.assertEqual(reopened.get_user("1001").code, u1.code)

    def test_draft_unique_per_user_and_isolated(self):
        self.store.get_or_create_user("a")
        self.store.get_or_create_user("b")
        d1 = self.store.create_or_get_draft("a")
        d1_again = self.store.create_or_get_draft("a")
        d2 = self.store.create_or_get_draft("b")
        self.assertEqual(d1.id, d1_again.id)  # کلیک مکرر = همان سفارش
        self.assertNotEqual(d1.id, d2.id)  # کاربرها جدا
        self.store.set_order_model(d1.id, "a", "model fox")
        self.assertEqual(self.store.get_order(d2.id).model, None)

    def test_duration_amounts_exact(self):
        self.assertEqual(vo.DURATIONS, {10: 35_000, 20: 60_000, 30: 80_000})
        self.assertEqual(vo.duration_button_text(10), "۱۰ ثانیه — ۳۵ هزار تومان")
        self.assertEqual(vo.duration_button_text(20), "۲۰ ثانیه — ۶۰ هزار تومان")
        self.assertEqual(vo.duration_button_text(30), "۳۰ ثانیه — ۸۰ هزار تومان")

    def test_receipt_attached_once_and_status_flow(self):
        self.store.get_or_create_user("a")
        order = self.store.create_or_get_draft("a")
        self.store.set_order_model(order.id, "a", "model plus")
        order = self.store.set_order_duration(order.id, "a", 20, 60_000)
        self.assertEqual(order.status, "awaiting_receipt")
        self.store.request_receipt(order.id, "a")
        self.assertTrue(self.store.attach_receipt(order.id, "a", "file-1"))
        self.assertFalse(self.store.attach_receipt(order.id, "a", "file-2"))  # تکراری نه
        saved = self.store.get_order(order.id)
        self.assertEqual(saved.status, "pending_review")  # هنوز پرداخت‌شده نیست
        self.assertEqual(saved.receipt_file_id, "file-1")
        self.store.update_status(order.id, "payment_approved")
        self.assertEqual(self.store.get_order(order.id).status, "payment_approved")

    def test_default_video_setting_persists(self):
        self.store.set_setting(vo.DEFAULT_VIDEO_FILE_KEY, "vid-9")
        self.store.set_setting(vo.DEFAULT_VIDEO_TEXT_KEY, "متن تست")
        self.store.set_setting(vo.DEFAULT_VIDEO_ENABLED_KEY, "1")
        reopened = Storage(self.db)
        self.assertEqual(reopened.get_setting(vo.DEFAULT_VIDEO_FILE_KEY), "vid-9")
        self.assertEqual(reopened.get_setting(vo.DEFAULT_VIDEO_TEXT_KEY), "متن تست")


class KeyboardsTest(unittest.TestCase):
    def test_model_keyboard_exact_buttons(self):
        data = inline_to_dict(build_model_keyboard())
        buttons = [b for row in data["inline_keyboard"] for b in row]
        self.assertEqual([b["text"] for b in buttons], ["model plus", "model fox", "model acod"])
        self.assertTrue(all(b["callback_data"].startswith("vm:") for b in buttons))

    def test_duration_and_receipt_keyboards(self):
        data = inline_to_dict(build_duration_keyboard())
        labels = [b["text"] for row in data["inline_keyboard"] for b in row]
        self.assertEqual(
            labels,
            ["۱۰ ثانیه — ۳۵ هزار تومان", "۲۰ ثانیه — ۶۰ هزار تومان", "۳۰ ثانیه — ۸۰ هزار تومان"],
        )
        receipt = inline_to_dict(build_receipt_keyboard(42))
        self.assertEqual(receipt["inline_keyboard"][0][0]["text"], "📤 ارسال رسید")
        self.assertEqual(receipt["inline_keyboard"][0][0]["callback_data"], "vr:42")


class VideoFlowTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self._tmp.name) / "flow.db")
        self.dp = build_dispatcher(TEST_SETTINGS, self.storage)
        self.bot = FakeBot()

    def tearDown(self):
        self._tmp.cleanup()

    async def _send(self, update):
        handled = await self.dp.feed_update(self.bot, update)  # type: ignore[arg-type]
        self.assertTrue(handled)

    async def test_full_order_journey_and_admin_approval(self):
        await self._send(make_update("/start", update_id=1))
        await self._send(make_update(texts.BTN_CREATE_VIDEO, update_id=2))
        intro = self.bot.sent[-1]
        self.assertIn("<b>", intro["text"])  # معرفی Bold با HTML
        self.assertIn("ساخت ویدیو با مدل هوش مصنوعی روباه", intro["text"])
        self.assertIsNotNone(intro["reply_markup"].inline_keyboard)

        await self._send(make_callback("vm:mfox", update_id=3))
        await self._send(make_callback("vd:20", update_id=4))
        payment = self.bot.sent[-1]
        self.assertIn("1111222233334444", payment["text"])  # کارت از تنظیمات تست
        self.assertIn("هزینه را به شماره کارت بالا پرداخت کنید و رسید را ارسال کنید", payment["text"])
        order = self.storage.list_user_orders("456")[0]
        self.assertEqual((order.model, order.duration_seconds, order.amount_toman), ("model fox", 20, 60_000))
        self.assertEqual(order.status, "awaiting_receipt")

        # کلیک مکرر روی مدت، سفارش تازه نمی‌سازد
        await self._send(make_callback("vd:20", update_id=5))
        self.assertEqual(len(self.storage.list_user_orders("456")), 1)

        await self._send(make_callback(f"vr:{order.id}", update_id=6))
        # متن به‌جای رسید: راهنمایی می‌گیرد، سفارش جلو نمی‌رود
        await self._send(make_update("این رسید من است", update_id=7))
        self.assertIn("رسید معتبر نیست", self.bot.sent[-1]["text"])
        self.assertEqual(self.storage.get_order(order.id).status, "awaiting_receipt")

        await self._send(make_photo_update(update_id=8))
        saved = self.storage.get_order(order.id)
        self.assertEqual(saved.status, "pending_review")
        self.assertEqual(saved.receipt_file_id, "receipt-file-1")
        # رسید + اطلاعات کامل برای مدیر (chat_id=999 از تنظیمات) رفت
        self.assertEqual(len(self.bot.photos), 1)
        self.assertEqual(str(self.bot.photos[0]["chat_id"]), "999")
        self.assertIn(self.storage.get_user("456").code, self.bot.photos[0]["caption"])
        self.assertIn("model fox", self.bot.photos[0]["caption"])

        # رسید تکراری برای همان سفارش ثبت نمی‌شود
        await self._send(make_photo_update(file_id="receipt-file-2", update_id=9))
        self.assertEqual(self.storage.get_order(order.id).receipt_file_id, "receipt-file-1")

        # کاربر سفارش خودش را می‌بیند
        await self._send(make_update(texts.BTN_MY_ORDERS, update_id=10))
        self.assertIn("در انتظار بررسی پرداخت", self.bot.sent[-1]["text"])

        # مدیر تأیید می‌کند؛ کاربر خبردار می‌شود
        await self._send(make_callback(f"va:{order.id}", user_id=999, chat_id=999, update_id=11))
        self.assertEqual(self.storage.get_order(order.id).status, "payment_approved")
        self.assertTrue(any("تأیید شد" in s["text"] for s in self.bot.sent))

    async def test_other_user_cannot_touch_my_order(self):
        self.storage.get_or_create_user("456", chat_id="123")
        order = self.storage.create_or_get_draft("456")
        self.storage.set_order_model(order.id, "456", "model plus")
        self.storage.set_order_duration(order.id, "456", 10, 35_000)
        # کاربر دیگر روی دکمه رسید سفارش من می‌زند
        await self._send(make_callback(f"vr:{order.id}", user_id=777, chat_id=777, update_id=20))
        self.assertFalse(self.storage.get_order(order.id).receipt_requested)
        self.assertTrue(any("مربوط به سفارش شما نیست" in (a["text"] or "") for a in self.bot.callback_answers))

    async def test_payment_not_configured_no_fake_card(self):
        dp = build_dispatcher(Settings(bot_token="x", admin_chat_id="999"), self.storage)
        bot = FakeBot()
        await dp.feed_update(bot, make_update(texts.BTN_CREATE_VIDEO, update_id=30))  # type: ignore[arg-type]
        await dp.feed_update(bot, make_callback("vm:mplus", update_id=31))  # type: ignore[arg-type]
        await dp.feed_update(bot, make_callback("vd:10", update_id=32))  # type: ignore[arg-type]
        self.assertIn("هنوز توسط مدیر تنظیم نشده است", bot.sent[-1]["text"])

    async def test_payment_guide_image_sent_when_file_exists(self):
        guide = Path(self._tmp.name) / "guide.jpg"
        guide.write_bytes(b"fake-jpeg-for-test")
        settings = Settings(
            bot_token="x",
            admin_chat_id="999",
            payment_card_number="1111222233334444",
            payment_card_holder="صاحب کارت تست",
            payment_guide_image=str(guide),
        )
        dp = build_dispatcher(settings, self.storage)
        bot = FakeBot()
        await dp.feed_update(bot, make_update(texts.BTN_CREATE_VIDEO, update_id=80))  # type: ignore[arg-type]
        await dp.feed_update(bot, make_callback("vm:mplus", update_id=81))  # type: ignore[arg-type]
        await dp.feed_update(bot, make_callback("vd:30", update_id=82))  # type: ignore[arg-type]
        # تصویر راهنما همراه متن پرداخت و دکمه رسید ارسال شده است
        self.assertEqual(len(bot.photos), 1)
        self.assertIn("هزینه را به شماره کارت بالا پرداخت کنید", bot.photos[0]["caption"])
        self.assertEqual(bot.photos[0]["reply_markup"].inline_keyboard[0][0].text, "📤 ارسال رسید")
        # و اگر فایل نباشد، بدون کرش فقط متن می‌آید (مسیر پیش‌فرض تست‌های دیگر)

    async def test_bundled_payment_card_image_used_by_default(self):
        # بدون PAYMENT_GUIDE_IMAGE، تصویر پیش‌فرض assets/payment_card.jpg می‌آید
        bundled = Path(__file__).resolve().parents[1] / "assets" / "payment_card.jpg"
        self.assertTrue(bundled.is_file())
        dp = build_dispatcher(
            Settings(
                bot_token="x",
                admin_chat_id="999",
                payment_card_number="1111222233334444",
                payment_card_holder="صاحب کارت تست",
            ),
            self.storage,
        )
        bot = FakeBot()
        await dp.feed_update(bot, make_update(texts.BTN_CREATE_VIDEO, update_id=90))  # type: ignore[arg-type]
        await dp.feed_update(bot, make_callback("vm:mfox", update_id=91))  # type: ignore[arg-type]
        await dp.feed_update(bot, make_callback("vd:10", update_id=92))  # type: ignore[arg-type]
        self.assertEqual(len(bot.photos), 1)
        self.assertTrue(str(bot.photos[0]["photo"]).endswith("payment_card.jpg"))
        self.assertIn("هزینه را به شماره کارت بالا پرداخت کنید", bot.photos[0]["caption"])

    async def test_admin_sets_default_video_and_users_receive_it(self):
        # کاربر عادی حق ندارد
        await self._send(make_update(vo.ADMIN_SET_VIDEO_COMMAND, user_id=456, chat_id=123, update_id=40))
        self.assertIn("فقط برای مدیر", self.bot.sent[-1]["text"])
        self.assertIsNone(self.storage.get_setting(vo.DEFAULT_VIDEO_FILE_KEY))

        # مدیر: دستور ← ویدیو ← متن
        await self._send(make_update(vo.ADMIN_SET_VIDEO_COMMAND, user_id=999, chat_id=999, update_id=41))
        await self._send(make_video_update(update_id=42))
        await self._send(make_update("ویدیوی معرفی روباه 🦊", user_id=999, chat_id=999, update_id=43))
        self.assertEqual(self.storage.get_setting(vo.DEFAULT_VIDEO_FILE_KEY), "default-video-1")
        self.assertEqual(self.storage.get_setting(vo.DEFAULT_VIDEO_ENABLED_KEY), "1")

        # حالا کاربر با «ساخت ویدیو» اول ویدیوی پیش‌فرض را می‌گیرد، بعد منوی مدل را
        self.bot.videos.clear()
        await self._send(make_update(texts.BTN_CREATE_VIDEO, user_id=555, chat_id=555, update_id=44))
        self.assertEqual(len(self.bot.videos), 1)
        self.assertEqual(self.bot.videos[0]["video"], "default-video-1")
        self.assertEqual(self.bot.videos[0]["caption"], "ویدیوی معرفی روباه 🦊")

        # حذف ویدیو توسط مدیر
        await self._send(make_update(vo.ADMIN_DELETE_VIDEO_COMMAND, user_id=999, chat_id=999, update_id=45))
        self.assertEqual(self.storage.get_setting(vo.DEFAULT_VIDEO_ENABLED_KEY), "0")
        self.bot.videos.clear()
        await self._send(make_update(texts.BTN_CREATE_VIDEO, user_id=556, chat_id=556, update_id=46))
        self.assertEqual(len(self.bot.videos), 0)


if __name__ == "__main__":
    unittest.main()
