# -*- coding: utf-8 -*-
"""هندلرهای ربات رسمی سروش‌پلاس (کتابخانه aiosplus روی Bot API رسمی).

ترتیب ثبت هندلرها مهم است: کتابخانه اولین هندلر منطبق را اجرا می‌کند،
پس دستورها و مسیرهای خاص (سفارش ویدیو، رسید، مدیر) قبل از مسیر عمومی
و fallback ثبت می‌شوند. هر کاربر فقط به سفارش‌های خودش دسترسی دارد.

در این مرحله مدل‌های ویدیوساز فقط گزینه انتخابی‌اند و هیچ API تولید
ویدیویی متصل نیست؛ سفارش پس از رسید، فقط با تأیید مدیر «پرداخت‌شده»
محسوب می‌شود.
"""
from __future__ import annotations

import logging
from pathlib import Path

from aiosplus import Bot, Dispatcher
from aiosplus.filters import Command, Text
from aiosplus.types import CallbackQuery, Message

import texts
import video_orders as vo
from bot_logic import route_message
from config import Settings
from keyboards import (
    build_admin_order_keyboard,
    build_duration_keyboard,
    build_main_keyboard,
    build_model_keyboard,
    build_receipt_keyboard,
)
from storage import (
    STATUS_PAYMENT_APPROVED,
    STATUS_PENDING_REVIEW,
    STATUS_REJECTED,
    Storage,
)

logger = logging.getLogger(__name__)


def _user_key(message: Message) -> str:
    """شناسه حساب سروش‌پلاس کاربر (از API)؛ هرگز کد شش‌رقمی داخلی نیست."""
    if message.from_user is not None:
        return str(message.from_user.id)
    return str(message.chat.id)


def _cb_user_key(callback: CallbackQuery) -> str:
    return str(callback.from_user.id)


def build_dispatcher(settings: Settings, storage: Storage | None = None) -> Dispatcher:
    """Dispatcher را می‌سازد و همه هندلرها را ثبت می‌کند."""
    store = storage if storage is not None else Storage()
    dp = Dispatcher()

    def is_admin_ids(user_id: object, chat_id: object) -> bool:
        if not settings.admin_chat_id:
            return False
        admin = str(settings.admin_chat_id).strip()
        return admin in {str(user_id), str(chat_id)}

    def ensure_user(message: Message):
        return store.get_or_create_user(
            _user_key(message),
            chat_id=str(message.chat.id),
            first_name=message.from_user.first_name if message.from_user else None,
        )

    async def _answer(message: Message) -> None:
        reply = route_message(message.text, settings)
        await message.answer(
            reply.text,
            reply_markup=build_main_keyboard() if reply.show_main_keyboard else None,
        )

    # ---------- دستورهای منو ----------
    @dp.message(Command("start"))
    async def cmd_start(message: Message) -> None:
        # اولین /start برای هر کاربر، شناسه شش‌رقمی پایدار او را می‌سازد
        user = ensure_user(message)
        logger.info(
            "شروع کاربر: splus_id=%s code=%s chat_id=%s",
            user.user_key,
            user.code,
            user.chat_id,
        )
        await _answer(message)

    @dp.message(Command("menu"))
    async def cmd_menu(message: Message) -> None:
        await _answer(message)

    @dp.message(Text(text=texts.MENU_TEXT_COMMAND))
    async def cmd_menu_fa(message: Message) -> None:
        await _answer(message)

    # ---------- دستورهای مدیریتی (فقط مدیر) ----------
    async def _deny_if_not_admin(message: Message) -> bool:
        if is_admin_ids(_user_key(message), message.chat.id):
            return False
        await message.answer(
            vo.ADMIN_NOT_CONFIGURED_TEXT if not settings.admin_chat_id else vo.NOT_ADMIN_TEXT,
            reply_markup=build_main_keyboard(),
        )
        return True

    @dp.message(Text(text=vo.ADMIN_SET_VIDEO_COMMAND))
    async def admin_set_video(message: Message) -> None:
        if await _deny_if_not_admin(message):
            return
        store.set_flow_state(_user_key(message), "admin_wait_video")
        await message.answer("🎬 لطفاً ویدیوی پیش‌فرض بخش «ساخت ویدیو» را ارسال کنید.")

    @dp.message(Text(text=vo.ADMIN_DELETE_VIDEO_COMMAND))
    async def admin_delete_video(message: Message) -> None:
        if await _deny_if_not_admin(message):
            return
        store.set_setting(vo.DEFAULT_VIDEO_FILE_KEY, None)
        store.set_setting(vo.DEFAULT_VIDEO_TEXT_KEY, None)
        store.set_setting(vo.DEFAULT_VIDEO_ENABLED_KEY, "0")
        store.clear_flow_state(_user_key(message))
        await message.answer("🗑 ویدیوی پیش‌فرض حذف و غیرفعال شد.")

    @dp.message(Text(text=vo.ADMIN_SET_VIDEO_TEXT_COMMAND))
    async def admin_set_video_text(message: Message) -> None:
        if await _deny_if_not_admin(message):
            return
        if not store.get_setting(vo.DEFAULT_VIDEO_FILE_KEY):
            await message.answer("هنوز ویدیویی تنظیم نشده است. اول «تنظیم ویدیو» را ارسال کنید.")
            return
        store.set_flow_state(_user_key(message), "admin_wait_video_text_only")
        await message.answer("✍️ متن جدید همراه ویدیو را ارسال کنید.")

    @dp.message(Text(text=vo.ADMIN_PENDING_COMMAND))
    async def admin_pending_orders(message: Message, bot: Bot) -> None:
        if await _deny_if_not_admin(message):
            return
        pending = store.list_orders(status=STATUS_PENDING_REVIEW, limit=5)
        if not pending:
            await message.answer("✅ در حال حاضر سفارشی در انتظار بررسی پرداخت نیست.")
            return
        await message.answer(f"🧾 {len(pending)} سفارش در انتظار بررسی پرداخت:")
        for order in pending:
            user = store.get_user(order.user_key)
            await bot.send_message(
                chat_id=message.chat.id,
                text=vo.order_summary(order, user),
                reply_markup=build_admin_order_keyboard(order.id),
            )

    @dp.message(Text(startswith="تأیید پرداخت"))
    async def admin_approve_text(message: Message, bot: Bot) -> None:
        if await _deny_if_not_admin(message):
            return
        await _admin_decide_text(message, bot, approve=True)

    @dp.message(Text(startswith="رد پرداخت"))
    async def admin_reject_text(message: Message, bot: Bot) -> None:
        if await _deny_if_not_admin(message):
            return
        await _admin_decide_text(message, bot, approve=False)

    async def _admin_decide_text(message: Message, bot: Bot, approve: bool) -> None:
        parts = (message.text or "").split()
        order = None
        if len(parts) >= 3 and parts[2].isdigit():
            order = store.get_order(int(parts[2]))
        if order is None or order.status != STATUS_PENDING_REVIEW:
            await message.answer("شناسه سفارش معتبرِ در انتظار بررسی پیدا نشد.")
            return
        await _apply_admin_decision(bot, order.id, approve)
        await message.answer(
            f"سفارش شماره {order.id} {'تأیید' if approve else 'رد'} شد."
        )

    async def _apply_admin_decision(bot: Bot, order_id: int, approve: bool) -> None:
        order = store.get_order(order_id)
        if order is None or order.status != STATUS_PENDING_REVIEW:
            return
        new_status = STATUS_PAYMENT_APPROVED if approve else STATUS_REJECTED
        store.update_status(order_id, new_status)
        user = store.get_user(order.user_key)
        if user and user.chat_id:
            text = (
                f"✅ پرداخت سفارش شماره {order_id} تأیید شد.\n"
                "سفارش شما در صف انجام قرار گرفت. (تولید ویدیو پس از اتصال سرویس انجام می‌شود.)"
                if approve
                else f"❌ پرداخت سفارش شماره {order_id} رد شد.\n"
                "اگر اشتباهی شده، با پشتیبانی در ارتباط باشید."
            )
            try:
                await bot.send_message(chat_id=int(user.chat_id), text=text)
            except Exception:
                logger.exception("اطلاع‌رسانی نتیجه بررسی به کاربر ممکن نشد (order=%s)", order_id)

    def _admin_flow_filter(message: Message, **_kwargs) -> bool:
        if not is_admin_ids(_user_key(message), message.chat.id):
            return False
        state = store.get_flow_state(_user_key(message))
        return state is not None and state[0] in {
            "admin_wait_video",
            "admin_wait_video_text",
            "admin_wait_video_text_only",
        }

    @dp.message(_admin_flow_filter)
    async def admin_flow_continue(message: Message) -> None:
        key = _user_key(message)
        state, payload = store.get_flow_state(key) or ("", None)
        if state == "admin_wait_video":
            if message.video is not None:
                store.set_flow_state(key, "admin_wait_video_text", message.video.file_id)
                await message.answer("✅ ویدیو دریافت شد. حالا متن همراه ویدیو را ارسال کنید.")
            else:
                await message.answer("لطفاً خودِ ویدیو را ارسال کنید (فایل ویدیویی).")
            return
        # admin_wait_video_text / admin_wait_video_text_only: منتظر متن هستیم
        if message.video is not None and state == "admin_wait_video_text":
            store.set_flow_state(key, "admin_wait_video_text", message.video.file_id)
            await message.answer("ویدیو جایگزین شد. متن همراه آن را ارسال کنید.")
            return
        if not message.text:
            await message.answer("لطفاً متن همراه ویدیو را به‌صورت پیام متنی ارسال کنید.")
            return
        if state == "admin_wait_video_text":
            store.set_setting(vo.DEFAULT_VIDEO_FILE_KEY, payload)
            store.set_setting(vo.DEFAULT_VIDEO_TEXT_KEY, message.text.strip())
            store.set_setting(vo.DEFAULT_VIDEO_ENABLED_KEY, "1")
        else:  # فقط متن عوض می‌شود، ویدیو قبلی می‌ماند
            store.set_setting(vo.DEFAULT_VIDEO_TEXT_KEY, message.text.strip())
            store.set_setting(vo.DEFAULT_VIDEO_ENABLED_KEY, "1")
        store.clear_flow_state(key)
        await message.answer("✅ ویدیوی پیش‌فرض و متن آن ذخیره شد و از این پس برای کاربران ارسال می‌شود.")

    # ---------- ساخت ویدیو و سفارش‌های من ----------
    @dp.message(Text(text=texts.BTN_CREATE_VIDEO))
    async def start_video_order(message: Message, bot: Bot) -> None:
        ensure_user(message)
        # ویدیوی پیش‌فرض مدیر (اگر تنظیم و فعال باشد) همراه متنش ارسال می‌شود
        if store.get_setting(vo.DEFAULT_VIDEO_ENABLED_KEY) == "1":
            file_id = store.get_setting(vo.DEFAULT_VIDEO_FILE_KEY)
            caption = store.get_setting(vo.DEFAULT_VIDEO_TEXT_KEY)
            if file_id:
                try:
                    await bot.send_video(
                        chat_id=message.chat.id, video=file_id, caption=caption
                    )
                except Exception:
                    logger.exception("ارسال ویدیوی پیش‌فرض ممکن نشد؛ فرایند سفارش ادامه می‌یابد")
        store.create_or_get_draft(_user_key(message))
        await bot.send_message(
            chat_id=message.chat.id,
            text=vo.VIDEO_INTRO_HTML,
            parse_mode="HTML",
            reply_markup=build_model_keyboard(),
        )

    @dp.message(Text(text=texts.BTN_MY_ORDERS))
    async def my_orders(message: Message) -> None:
        user = ensure_user(message)
        orders = store.list_user_orders(user.user_key, limit=10)
        await message.answer(vo.user_orders_text(orders, user), reply_markup=build_main_keyboard())

    # ---------- رسید: تصویر و محتوای نامعتبر ----------
    def _has_receipt_candidate(message: Message, **_kwargs) -> bool:
        return store.find_receipt_candidate(_user_key(message)) is not None

    @dp.message(lambda m, **_kw: bool(m.photo))
    async def on_photo(message: Message, bot: Bot) -> None:
        ensure_user(message)
        candidate = store.find_receipt_candidate(_user_key(message))
        if candidate is None:
            await message.answer(
                "برای ثبت رسید، اول از بخش «ساخت ویدیو» سفارش را کامل کنید و روی «📤 ارسال رسید» بزنید.",
                reply_markup=build_main_keyboard(),
            )
            return
        photo = max(message.photo, key=lambda p: (p.file_size or 0, p.width * p.height))
        if not store.attach_receipt(candidate.id, _user_key(message), photo.file_id):
            await message.answer(vo.RECEIPT_DUPLICATE_TEXT, reply_markup=build_main_keyboard())
            return
        await message.answer(vo.RECEIPT_RECEIVED_TEXT, reply_markup=build_main_keyboard())
        await _notify_admin_receipt(bot, candidate.id)

    async def _notify_admin_receipt(bot: Bot, order_id: int) -> None:
        order = store.get_order(order_id)
        if order is None:
            return
        if not settings.admin_chat_id:
            logger.error(
                "ADMIN_CHAT_ID تنظیم نشده است؛ رسید سفارش %s در صف «در انتظار بررسی پرداخت» "
                "باقی ماند و برای مدیر ارسال نشد.",
                order_id,
            )
            return
        user = store.get_user(order.user_key)
        try:
            await bot.send_photo(
                chat_id=settings.admin_chat_id,
                photo=order.receipt_file_id,
                caption=vo.order_summary(order, user),
                reply_markup=build_admin_order_keyboard(order.id),
            )
        except Exception:
            logger.exception(
                "ارسال رسید سفارش %s برای مدیر ممکن نشد؛ سفارش در صف بررسی باقی است.",
                order_id,
            )

    # ---------- دکمه‌های شیشه‌ای (Callback) ----------
    async def _cb_answer(bot: Bot, callback: CallbackQuery, text: str | None = None, alert: bool = False) -> None:
        try:
            await bot.answer_callback_query(
                callback_query_id=callback.id, text=text, show_alert=alert or None
            )
        except Exception:
            logger.exception("answerCallbackQuery ممکن نشد")

    @dp.callback_query(Text(startswith="vm:"))
    async def on_model_chosen(callback: CallbackQuery, bot: Bot) -> None:
        key = callback.data.split(":", 1)[1] if callback.data else ""
        model = vo.MODELS.get(key)
        chat_id = callback.message.chat.id if callback.message else None
        if model is None or chat_id is None:
            await _cb_answer(bot, callback, "گزینه نامعتبر است.", alert=True)
            return
        user_key = _cb_user_key(callback)
        store.get_or_create_user(user_key, chat_id=str(chat_id))
        draft = store.create_or_get_draft(user_key)
        if draft.status != "draft" and draft.receipt_file_id:
            await _cb_answer(bot, callback, vo.RECEIPT_DUPLICATE_TEXT, alert=True)
            return
        order = store.set_order_model(draft.id, user_key, model) or draft
        await _cb_answer(bot, callback, f"مدل {model} انتخاب شد.")
        await bot.send_message(
            chat_id=chat_id,
            text=f"✅ مدل «{model}» برای سفارش شماره {order.id} انتخاب شد.\n"
            "حالا مدت ویدیو را انتخاب کنید:",
            reply_markup=build_duration_keyboard(),
        )

    @dp.callback_query(Text(startswith="vd:"))
    async def on_duration_chosen(callback: CallbackQuery, bot: Bot) -> None:
        chat_id = callback.message.chat.id if callback.message else None
        try:
            seconds = int(callback.data.split(":", 1)[1])
        except (ValueError, IndexError):
            seconds = -1
        if chat_id is None or seconds not in vo.DURATIONS:
            await _cb_answer(bot, callback, "گزینه نامعتبر است.", alert=True)
            return
        user_key = _cb_user_key(callback)
        draft = store.get_active_order(user_key)
        if draft is None or not draft.model:
            await _cb_answer(bot, callback, "اول از «ساخت ویدیو» مدل را انتخاب کنید.", alert=True)
            return
        # کلیک مکرر روی مدت، سفارش تازه نمی‌سازد؛ همان سفارش به‌روز می‌شود
        order = store.set_order_duration(draft.id, user_key, seconds, vo.DURATIONS[seconds]) or draft
        await _cb_answer(bot, callback, "مدت و مبلغ ثبت شد.")
        await _send_payment(bot, chat_id, order)

    async def _send_payment(bot: Bot, chat_id: int, order) -> None:
        text = vo.build_payment_text(order, settings)
        if text is None:
            await bot.send_message(chat_id=chat_id, text=vo.PAYMENT_NOT_CONFIGURED_TEXT)
            return
        markup = build_receipt_keyboard(order.id)
        # تصویر راهنمای پرداخت: اول تنظیم مدیر، وگرنه تصویر پیش‌فرض داخل پروژه
        bundled = Path(__file__).resolve().parent / "assets" / "payment_card.jpg"
        guide = settings.payment_guide_image or (str(bundled) if bundled.is_file() else None)
        if guide and Path(guide).is_file():
            try:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=str(Path(guide)),
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
                return
            except Exception:
                logger.exception("ارسال تصویر راهنمای پرداخت ممکن نشد؛ متن پرداخت ارسال می‌شود")
        await bot.send_message(
            chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=markup
        )

    @dp.callback_query(Text(startswith="vr:"))
    async def on_send_receipt_clicked(callback: CallbackQuery, bot: Bot) -> None:
        chat_id = callback.message.chat.id if callback.message else None
        try:
            order_id = int(callback.data.split(":", 1)[1])
        except (ValueError, IndexError):
            order_id = -1
        order = store.get_order(order_id)
        if chat_id is None or order is None or order.user_key != _cb_user_key(callback):
            await _cb_answer(bot, callback, "این دکمه مربوط به سفارش شما نیست.", alert=True)
            return
        if order.status != "awaiting_receipt":
            await _cb_answer(bot, callback, vo.RECEIPT_DUPLICATE_TEXT, alert=True)
            return
        store.request_receipt(order.id, order.user_key)
        await _cb_answer(bot, callback)
        await bot.send_message(chat_id=chat_id, text=vo.RECEIPT_PROMPT_TEXT)

    @dp.callback_query(Text(startswith="va:"))
    async def on_admin_approve(callback: CallbackQuery, bot: Bot) -> None:
        await _admin_callback(callback, bot, approve=True)

    @dp.callback_query(Text(startswith="vrj:"))
    async def on_admin_reject(callback: CallbackQuery, bot: Bot) -> None:
        await _admin_callback(callback, bot, approve=False)

    async def _admin_callback(callback: CallbackQuery, bot: Bot, approve: bool) -> None:
        chat_id = callback.message.chat.id if callback.message else 0
        if not is_admin_ids(_cb_user_key(callback), chat_id):
            await _cb_answer(bot, callback, vo.NOT_ADMIN_TEXT, alert=True)
            return
        try:
            order_id = int(callback.data.split(":", 1)[1])
        except (ValueError, IndexError):
            order_id = -1
        order = store.get_order(order_id)
        if order is None or order.status != STATUS_PENDING_REVIEW:
            await _cb_answer(bot, callback, "این سفارش قبلاً بررسی شده است.", alert=True)
            return
        await _apply_admin_decision(bot, order_id, approve)
        await _cb_answer(bot, callback, "پرداخت تأیید شد ✅" if approve else "پرداخت رد شد ❌")

    # ---------- بقیه دکمه‌های منوی اصلی و fallback ----------
    @dp.message(
        Text(
            text=[
                texts.BTN_CREATE_IMAGE,
                texts.BTN_FREE_CREDIT,
                texts.BTN_SAMPLES,
                texts.BTN_SUPPORT,
                texts.BTN_GROUP,
                texts.BTN_CHANNEL,
            ]
        )
    )
    async def on_main_menu_button(message: Message) -> None:
        await _answer(message)

    # متن/فایل غیرعکس در حالی که ربات منتظر تصویر رسید این کاربر است
    @dp.message(_has_receipt_candidate)
    async def on_invalid_receipt_content(message: Message) -> None:
        await message.answer(vo.RECEIPT_INVALID_TEXT)

    @dp.message()
    async def fallback(message: Message) -> None:
        logger.info("پیام ناشناخته دریافت شد (chat_id=%s)", message.chat.id)
        await _answer(message)

    return dp
