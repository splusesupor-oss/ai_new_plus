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
    build_broadcast_keyboard,
    build_deliver_keyboard,
    build_duration_keyboard,
    build_main_keyboard,
    build_model_keyboard,
    build_order_type_keyboard,
    build_receipt_keyboard,
)
from storage import (
    STATUS_PAYMENT_APPROVED,
    STATUS_PENDING_REVIEW,
    STATUS_PROCESSING,
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

    def is_admin_ids(user_id: object, chat_id: object, username: object = None) -> bool:
        # مدیر با شناسه عددی چت/حساب یا با یوزرنیم شناخته می‌شود
        if settings.admin_chat_id:
            admin = str(settings.admin_chat_id).strip()
            if admin in {str(user_id), str(chat_id)}:
                return True
        if settings.admin_username and username:
            return str(username).lstrip("@").lower() == settings.admin_username.lstrip("@").lower()
        return False

    def ensure_user(message: Message):
        fu = message.from_user
        display = None
        if fu is not None:
            display = getattr(fu, "full_name", None) or fu.first_name
        return store.get_or_create_user(
            _user_key(message),
            chat_id=str(message.chat.id),
            first_name=fu.first_name if fu else None,
            username=fu.username if fu else None,
            display_name=display,
        )

    def _is_admin(message: Message) -> bool:
        uname = message.from_user.username if message.from_user else None
        return is_admin_ids(_user_key(message), message.chat.id, uname)

    def _is_blocked(message: Message) -> bool:
        # مدیر اصلی هرگز مسدود نمی‌شود
        if _is_admin(message):
            return False
        user = store.get_user(_user_key(message))
        return bool(user and user.is_blocked)

    async def _answer(message: Message) -> None:
        reply = route_message(message.text, settings)
        await message.answer(
            reply.text,
            reply_markup=build_main_keyboard() if reply.show_main_keyboard else None,
        )

    # ---------- نگه‌دار مسدودی (قبل از همه) ----------
    @dp.message(lambda m, **_kw: store.get_user(_user_key(m)) is not None and _is_blocked(m))
    async def blocked_guard(message: Message) -> None:
        await message.answer(vo.BLOCKED_TEXT)

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
        uname = message.from_user.username if message.from_user else None
        if is_admin_ids(_user_key(message), message.chat.id, uname):
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
                text=vo.order_admin_html(order, user),
                parse_mode="HTML",
                reply_markup=build_admin_order_keyboard(order.id),
            )

    @dp.message(Text(text=vo.ADMIN_MEMBERS_COMMAND))
    async def admin_members(message: Message) -> None:
        if await _deny_if_not_admin(message):
            return
        users = store.list_users()
        full = vo.members_text(users)
        # پیام‌های بلند در چند بخش ارسال می‌شوند تا سقف API رد نشود
        chunk = ""
        for line in full.split("\n"):
            if len(chunk) + len(line) + 1 > 3400:
                await message.answer(chunk, parse_mode="HTML")
                chunk = ""
            chunk += line + "\n"
        if chunk.strip():
            await message.answer(chunk, parse_mode="HTML")

    @dp.message(Text(text=vo.ADMIN_READY_COMMAND))
    async def admin_ready_orders(message: Message, bot: Bot) -> None:
        if await _deny_if_not_admin(message):
            return
        ready = store.list_orders(status=STATUS_PAYMENT_APPROVED, limit=5)
        if not ready:
            await message.answer("در حال حاضر سفارش تأییدشده‌ای منتظر تحویل نیست.")
            return
        for order in ready:
            user = store.get_user(order.user_key)
            await bot.send_message(
                chat_id=message.chat.id,
                text=vo.order_admin_html(order, user),
                parse_mode="HTML",
                reply_markup=build_deliver_keyboard(order.id),
            )

    @dp.message(Text(text=vo.ADMIN_BROADCAST_COMMAND))
    async def admin_broadcast_start(message: Message) -> None:
        if await _deny_if_not_admin(message):
            return
        store.set_flow_state(_user_key(message), "admin_wait_broadcast_text")
        await message.answer(
            "📢 متن اطلاع‌رسانی را ارسال کنید.\n"
            "برای Bold شدن بخشی از متن، آن را بین ** بنویسید؛ مثال: سلام **اطلاعیه مهم**"
        )

    def _fa_digits(text: str) -> str:
        return text.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))

    def _block_filter(message: Message, **_kw) -> bool:
        parts = _fa_digits((message.text or "").strip()).split()
        return (
            len(parts) in (2, 3)
            and len(parts[0]) == 6
            and parts[0].isdigit()
            and (parts[1] == "مسدود" or parts[1:] == ["رفع", "مسدودیت"])
        )

    @dp.message(_block_filter)
    async def admin_block_user(message: Message) -> None:
        if await _deny_if_not_admin(message):
            return
        parts = _fa_digits((message.text or "").strip()).split()
        code = parts[0]
        unblock = parts[1:] == ["رفع", "مسدودیت"]
        user = store.set_blocked_by_code(code, blocked=not unblock)
        if user is None:
            await message.answer(f"کاربری با شناسه شش‌رقمی {code} پیدا نشد.")
            return
        await message.answer(
            f"کاربر {vo.user_display(user)} (کد {code}) "
            + ("از مسدودیت خارج شد ✅" if unblock else "مسدود شد 🚫")
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
        await _apply_admin_decision(bot, order.id, approve, admin_chat_id=message.chat.id)
        await message.answer(
            f"سفارش شماره {order.id} {'تأیید' if approve else 'رد'} شد."
        )

    async def _apply_admin_decision(
        bot: Bot, order_id: int, approve: bool, admin_chat_id: object = None
    ) -> None:
        order = store.get_order(order_id)
        if order is None or order.status != STATUS_PENDING_REVIEW:
            return
        new_status = STATUS_PAYMENT_APPROVED if approve else STATUS_REJECTED
        store.update_status(order_id, new_status)
        user = store.get_user(order.user_key)
        if approve and admin_chat_id is not None:
            # از مدیر خواسته می‌شود سفارش را تحویل دهد
            approved = store.get_order(order_id)
            try:
                await bot.send_message(
                    chat_id=admin_chat_id,
                    text=vo.order_admin_html(approved, user)
                    + "\n\n<b>پرداخت تأیید شد. لطفاً سفارش را تحویل دهید:</b>",
                    parse_mode="HTML",
                    reply_markup=build_deliver_keyboard(order_id),
                )
            except Exception:
                logger.exception("ارسال درخواست تحویل سفارش %s برای مدیر ممکن نشد", order_id)
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
        uname = message.from_user.username if message.from_user else None
        if not is_admin_ids(_user_key(message), message.chat.id, uname):
            return False
        state = store.get_flow_state(_user_key(message))
        return state is not None and (
            state[0].startswith("admin_wait_delivery_video")
            or state[0]
            in {
                "admin_wait_video",
                "admin_wait_video_text",
                "admin_wait_video_text_only",
            }
        )

    @dp.message(_admin_flow_filter)
    async def admin_flow_continue(message: Message, bot: Bot) -> None:
        key = _user_key(message)
        state, payload = store.get_flow_state(key) or ("", None)
        if state.startswith("admin_wait_delivery_video"):
            # مدیر در حال تحویل ویدیوی نهایی یک سفارش است
            try:
                order_id = int(state.rsplit(":", 1)[1])
            except (ValueError, IndexError):
                store.clear_flow_state(key)
                return
            if message.video is None:
                await message.answer("لطفاً ویدیوی نهایی سفارش را ارسال کنید (فایل ویدیویی).")
                return
            order = store.get_order(order_id)
            target = store.get_user(order.user_key) if order else None
            if order is None or target is None or not target.chat_id:
                store.clear_flow_state(key)
                await message.answer("کاربر صاحب سفارش پیدا نشد؛ تحویل ممکن نیست.")
                return
            try:
                await bot.send_video(
                    chat_id=int(target.chat_id),
                    video=message.video.file_id,
                    caption=f"🎬 سفارش ویدیوی شما آماده و تحویل داده شد!\nشماره سفارش: {order_id}",
                )
            except Exception:
                logger.exception("تحویل ویدیوی سفارش %s به کاربر ممکن نشد", order_id)
                await message.answer("ارسال ویدیو به کاربر ناموفق بود؛ دوباره تلاش کنید.")
                return
            store.complete_delivery(order_id, message.video.file_id)
            store.clear_flow_state(key)
            await message.answer(f"✅ ویدیوی سفارش شماره {order_id} برای کاربر ارسال و سفارش تکمیل شد.")
            return
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

    def _broadcast_flow_filter(message: Message, **_kw) -> bool:
        if not _is_admin(message):
            return False
        state = store.get_flow_state(_user_key(message))
        return state is not None and state[0] == "admin_wait_broadcast_text"

    @dp.message(_broadcast_flow_filter)
    async def admin_broadcast_text(message: Message, bot: Bot) -> None:
        if not message.text:
            await message.answer("لطفاً متن اطلاع‌رسانی را به‌صورت پیام متنی ارسال کنید.")
            return
        raw = message.text.strip()
        store.set_flow_state(_user_key(message), "admin_wait_broadcast_confirm", raw)
        # پیش‌نمایش دقیقاً همان‌طور که برای اعضا می‌رود، با دکمه تأیید/لغو
        await bot.send_message(
            chat_id=message.chat.id,
            text=vo.broadcast_to_html(raw),
            parse_mode="HTML",
            reply_markup=build_broadcast_keyboard(),
        )

    def _order_text_flow_filter(message: Message, **_kw) -> bool:
        if _is_admin(message):
            return False
        state = store.get_flow_state(_user_key(message))
        return state is not None and state[0].startswith("wait_order_text")

    @dp.message(_order_text_flow_filter)
    async def user_order_text(message: Message, bot: Bot) -> None:
        key = _user_key(message)
        state, _payload = store.get_flow_state(key) or ("", None)
        try:
            order_id = int(state.rsplit(":", 1)[1])
        except (ValueError, IndexError):
            store.clear_flow_state(key)
            return
        text = (message.text or "").strip()
        if text in (texts.MENU_TEXT_COMMAND, "/start", "/menu", "لغو"):
            store.clear_flow_state(key)
            await _answer(message)
            return
        if len(text) < vo.MIN_ORDER_TEXT_LENGTH:
            await message.answer(
                f"متن کوتاه است: {len(text)} کاراکتر. حداقل {vo.MIN_ORDER_TEXT_LENGTH} کاراکتر بنویسید."
            )
            return
        order = store.set_order_content(order_id, key, "text", text)
        store.clear_flow_state(key)
        if order is None:
            await message.answer("سفارش پیدا نشد؛ از «ساخت ویدیو» دوباره شروع کنید.")
            return
        await bot.send_message(
            chat_id=message.chat.id,
            text="✅ متن سفارش ثبت شد. حالا مدل ویدیوساز را انتخاب کنید:",
            reply_markup=build_model_keyboard(),
        )

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
            reply_markup=build_order_type_keyboard(),
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
        flow = store.get_flow_state(_user_key(message))
        if flow is not None and flow[0].startswith("wait_order_photo"):
            # عکسِ درخواستیِ سفارش «ساخت ویدیو با عکس» + متن توضیحی در کپشن
            try:
                order_id = int(flow[0].rsplit(":", 1)[1])
            except (ValueError, IndexError):
                store.clear_flow_state(_user_key(message))
                return
            caption = (message.caption or "").strip()
            if not caption:
                await message.answer(
                    "عکس باید متن توضیحی داشته باشد؛ عکس را با توضیح در کپشن دوباره ارسال کنید."
                )
                return
            photo = max(message.photo, key=lambda p: (p.file_size or 0, p.width * p.height))
            order = store.set_order_content(order_id, _user_key(message), "photo", caption, photo.file_id)
            store.clear_flow_state(_user_key(message))
            if order is None:
                await message.answer("سفارش پیدا نشد؛ از «ساخت ویدیو» دوباره شروع کنید.")
                return
            await bot.send_message(
                chat_id=message.chat.id,
                text="✅ عکس و توضیح سفارش ثبت شد. حالا مدل ویدیوساز را انتخاب کنید:",
                reply_markup=build_model_keyboard(),
            )
            return
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
                caption=vo.order_admin_html(order, user, full_text=False),
                parse_mode="HTML",
                reply_markup=build_admin_order_keyboard(order.id),
            )
            # متن کامل درخواست جداگانه می‌آید تا سقف کپشن عکس چیزی را نبرد
            await bot.send_message(
                chat_id=settings.admin_chat_id,
                text=vo.order_admin_html(order, user, full_text=True),
                parse_mode="HTML",
            )
            if order.order_type == "photo" and order.request_photo_file_id:
                await bot.send_photo(
                    chat_id=settings.admin_chat_id,
                    photo=order.request_photo_file_id,
                    caption=f"🖼 عکس درخواستی کاربر برای سفارش شماره {order.id}",
                )
        except Exception:
            logger.exception(
                "ارسال رسید سفارش %s برای مدیر ممکن نشد؛ سفارش در صف بررسی باقی است.",
                order_id,
            )

    # ---------- دکمه‌های شیشه‌ای (Callback) ----------
    def _cb_blocked(callback: CallbackQuery, **_kw) -> bool:
        chat_id = callback.message.chat.id if callback.message else 0
        if is_admin_ids(_cb_user_key(callback), chat_id, callback.from_user.username):
            return False
        user = store.get_user(_cb_user_key(callback))
        return bool(user and user.is_blocked)

    @dp.callback_query(_cb_blocked)
    async def blocked_callback_guard(callback: CallbackQuery, bot: Bot) -> None:
        await _cb_answer(bot, callback, vo.BLOCKED_TEXT, alert=True)

    @dp.callback_query(Text(startswith="vt:"))
    async def on_order_type_chosen(callback: CallbackQuery, bot: Bot) -> None:
        kind = callback.data.split(":", 1)[1] if callback.data else ""
        chat_id = callback.message.chat.id if callback.message else None
        if kind not in vo.ORDER_TYPES or chat_id is None:
            await _cb_answer(bot, callback, "گزینه نامعتبر است.", alert=True)
            return
        user_key = _cb_user_key(callback)
        store.get_or_create_user(
            user_key,
            chat_id=str(chat_id),
            username=callback.from_user.username,
            display_name=getattr(callback.from_user, "full_name", None),
        )
        draft = store.create_or_get_draft(user_key)
        if draft.receipt_file_id:
            await _cb_answer(bot, callback, vo.RECEIPT_DUPLICATE_TEXT, alert=True)
            return
        store.set_flow_state(user_key, f"wait_order_{kind}:{draft.id}")
        await _cb_answer(bot, callback, f"«{vo.ORDER_TYPES[kind]}» انتخاب شد.")
        prompt = vo.ORDER_TEXT_PROMPT if kind == "text" else vo.ORDER_PHOTO_PROMPT
        await bot.send_message(chat_id=chat_id, text=prompt)

    @dp.callback_query(Text(startswith="vdl:"))
    async def on_deliver_clicked(callback: CallbackQuery, bot: Bot) -> None:
        chat_id = callback.message.chat.id if callback.message else 0
        if not is_admin_ids(_cb_user_key(callback), chat_id, callback.from_user.username):
            await _cb_answer(bot, callback, vo.NOT_ADMIN_TEXT, alert=True)
            return
        try:
            order_id = int(callback.data.split(":", 1)[1])
        except (ValueError, IndexError):
            order_id = -1
        order = store.get_order(order_id)
        if order is None or order.status not in (STATUS_PAYMENT_APPROVED, STATUS_PROCESSING):
            await _cb_answer(bot, callback, "این سفارش آماده تحویل نیست.", alert=True)
            return
        store.update_status(order_id, STATUS_PROCESSING)
        store.set_flow_state(_cb_user_key(callback), f"admin_wait_delivery_video:{order_id}")
        await _cb_answer(bot, callback)
        await bot.send_message(
            chat_id=chat_id,
            text=f"🎬 ویدیوی نهایی سفارش شماره {order_id} را ارسال کنید تا برای کاربر فرستاده شود.",
        )

    @dp.callback_query(Text(startswith="vbc:"))
    async def on_broadcast_decision(callback: CallbackQuery, bot: Bot) -> None:
        chat_id = callback.message.chat.id if callback.message else 0
        if not is_admin_ids(_cb_user_key(callback), chat_id, callback.from_user.username):
            await _cb_answer(bot, callback, vo.NOT_ADMIN_TEXT, alert=True)
            return
        action = callback.data.split(":", 1)[1] if callback.data else ""
        admin_key = _cb_user_key(callback)
        flow = store.get_flow_state(admin_key)
        if action == "cancel":
            store.clear_flow_state(admin_key)
            await _cb_answer(bot, callback, "لغو شد.")
            await bot.send_message(chat_id=chat_id, text="اطلاع‌رسانی لغو شد ❌")
            return
        if flow is None or flow[0] != "admin_wait_broadcast_confirm" or not flow[1]:
            await _cb_answer(bot, callback, "متن اطلاع‌رسانی پیدا نشد؛ دوباره «اطلاع رسانی» را بزنید.", alert=True)
            return
        html_text = vo.broadcast_to_html(flow[1])
        store.clear_flow_state(admin_key)
        sent = failed = 0
        for member in store.list_users():
            if member.is_blocked or not member.chat_id:
                continue
            try:
                await bot.send_message(chat_id=int(member.chat_id), text=html_text, parse_mode="HTML")
                sent += 1
            except Exception:
                failed += 1
                logger.exception("ارسال اطلاع‌رسانی به کاربر %s ممکن نشد", member.user_key)
        await _cb_answer(bot, callback, "ارسال انجام شد ✅")
        await bot.send_message(
            chat_id=chat_id,
            text=f"📢 اطلاع‌رسانی ارسال شد. موفق: {sent} | ناموفق: {failed}",
        )

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
        store.get_or_create_user(
            user_key,
            chat_id=str(chat_id),
            username=callback.from_user.username,
            display_name=getattr(callback.from_user, "full_name", None),
        )
        draft = store.create_or_get_draft(user_key)
        if not draft.order_type:
            await _cb_answer(bot, callback, "اول نوع سفارش (با متن یا با عکس) را انتخاب کنید.", alert=True)
            await bot.send_message(
                chat_id=chat_id, text=vo.TYPE_BUTTON_TEXT, reply_markup=build_order_type_keyboard()
            )
            return
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
        if not is_admin_ids(_cb_user_key(callback), chat_id, callback.from_user.username):
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
        await _apply_admin_decision(bot, order_id, approve, admin_chat_id=chat_id)
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
