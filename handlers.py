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

import asyncio
import hashlib
import logging
from pathlib import Path

from aiosplus import Bot, Dispatcher
from aiosplus.filters import Command, Text
from aiosplus.types import CallbackQuery, Message

import image_orders as io
import support as sup
import texts
import video_orders as vo
from bot_logic import route_message
from config import Settings
from keyboards import (
    build_admin_order_keyboard,
    build_broadcast_keyboard,
    build_channel_keyboard,
    build_deliver_keyboard,
    build_duration_keyboard,
    build_group_keyboard,
    build_image_admin_keyboard,
    build_image_mode_keyboard,
    build_image_model_keyboard,
    build_main_keyboard,
    build_model_keyboard,
    build_order_type_keyboard,
    build_receipt_keyboard,
    build_rules_keyboard,
)
from storage import (
    STATUS_COMPLETED,
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

    # ---------- دروازه قوانین: قبل از تأیید، هیچ منو/دکمه‌ای باز نمی‌شود ----------
    async def _send_rules(bot: Bot, chat_id: int) -> None:
        img = Path(__file__).resolve().parent / "assets" / "rules.jpg"
        markup = build_rules_keyboard()
        if img.is_file():
            try:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=str(img),
                    caption=texts.RULES_CAPTION,
                    reply_markup=markup,
                )
                return
            except Exception:
                logger.exception("ارسال عکس قوانین ممکن نشد؛ متن قوانین ارسال می‌شود")
        await bot.send_message(chat_id=chat_id, text=texts.RULES_CAPTION, reply_markup=markup)

    # ---------- ارسال سریع عکس‌های محلی با کش file_id ----------
    def _local_photo_cache_key(prefix: str, path: Path) -> str:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return f"photo_file_id:{prefix}:{digest}"

    async def _send_local_photo_cached(
        bot: Bot,
        chat_id: object,
        path: Path,
        cache_prefix: str,
        caption: str | None = None,
        parse_mode: str | None = None,
        reply_markup: object = None,
    ):
        """عکس محلی را بار اول آپلود و دفعات بعد با file_id می‌فرستد.

        آپلود تکراری فایل (مثل کارت پرداخت) روی شبکه گوشی کند است؛ وقتی
        سروش‌پلاس file_id داد، همان ذخیره و برای ارسال‌های بعدی استفاده
        می‌شود تا مرحله پرداخت تقریباً فوری شود.
        """
        key = _local_photo_cache_key(cache_prefix, path)
        cached = store.get_setting(key)
        if cached:
            try:
                return await bot.send_photo(
                    chat_id=chat_id,
                    photo=cached,
                    caption=caption,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                )
            except Exception:
                logger.warning("file_id ذخیره‌شده عکس پذیرفته نشد؛ آپلود مجدد انجام می‌شود")
                store.set_setting(key, None)
        sent = await bot.send_photo(
            chat_id=chat_id,
            photo=str(path),
            caption=caption,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
        photos = getattr(sent, "photo", None)
        if photos:
            try:
                best = max(photos, key=lambda p: (p.file_size or 0, p.width * p.height))
                if best.file_id:
                    store.set_setting(key, best.file_id)
            except Exception:
                logger.exception("ذخیره file_id عکس ممکن نشد؛ ارسال انجام شد")
        return sent

    def _is_start_or_menu(message: Message) -> bool:
        raw = (message.text or "").strip()
        first = raw.split(maxsplit=1)[0].split("@", 1)[0].lower() if raw else ""
        return first in ("/start", "/menu") or raw == texts.MENU_TEXT_COMMAND

    def _rules_guard_filter(message: Message, **_kw) -> bool:
        if _is_start_or_menu(message):
            return False
        return not store.has_accepted_rules(_user_key(message))

    # ---------- نگه‌دار مسدودی (قبل از همه) ----------
    @dp.message(lambda m, **_kw: store.get_user(_user_key(m)) is not None and _is_blocked(m))
    async def blocked_guard(message: Message) -> None:
        await message.answer(vo.BLOCKED_TEXT)

    @dp.message(_rules_guard_filter)
    async def rules_guard(message: Message, bot: Bot) -> None:
        # هر پیام/دکمه‌ای قبل از تأیید قوانین فقط عکس قوانین را می‌بیند
        ensure_user(message)
        await _send_rules(bot, message.chat.id)

    # ---------- دستورهای منو ----------
    @dp.message(Command("start"))
    async def cmd_start(message: Message, bot: Bot) -> None:
        # اولین /start برای هر کاربر، شناسه شش‌رقمی پایدار او را می‌سازد
        user = ensure_user(message)
        logger.info(
            "شروع کاربر: splus_id=%s code=%s chat_id=%s",
            user.user_key,
            user.code,
            user.chat_id,
        )
        if not user.rules_accepted:
            await _send_rules(bot, message.chat.id)
            return
        await _answer(message)

    @dp.message(Command("menu"))
    async def cmd_menu(message: Message, bot: Bot) -> None:
        user = ensure_user(message)
        if not user.rules_accepted:
            await _send_rules(bot, message.chat.id)
            return
        await _answer(message)

    @dp.message(Text(text=texts.MENU_TEXT_COMMAND))
    async def cmd_menu_fa(message: Message, bot: Bot) -> None:
        user = ensure_user(message)
        if not user.rules_accepted:
            await _send_rules(bot, message.chat.id)
            return
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
            await message.answer("✅ در حال حاضر سفارشی در انتظار بررسی نیست.")
            return
        await message.answer(f"🧾 {len(pending)} سفارش در انتظار بررسی:")
        for order in pending:
            user = store.get_user(order.user_key)
            if order.service == "image":
                # سفارش عکس پرداخت ندارد: جزئیات و دکمه‌های مخصوص خودش می‌رود
                details = io.image_admin_html(
                    order, user, store.ensure_daily_credit(order.user_key)
                )
                if order.request_photo_file_id:
                    try:
                        await bot.send_photo(
                            chat_id=message.chat.id,
                            photo=order.request_photo_file_id,
                            caption=details[:1000],
                            parse_mode="HTML",
                            reply_markup=build_image_admin_keyboard(order.id),
                        )
                        continue
                    except Exception:
                        logger.exception("ارسال عکس سفارش تصویر برای مدیر ممکن نشد؛ متن می‌رود")
                await bot.send_message(
                    chat_id=message.chat.id,
                    text=details,
                    parse_mode="HTML",
                    reply_markup=build_image_admin_keyboard(order.id),
                )
                continue
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
        if order.service == "image":
            await message.answer(
                "این سفارش تصویر است و پرداخت ندارد؛ از دکمه‌های «🎨 ارسال تصویر نهایی» "
                "یا «❌ رد سفارش» روی پیام همان سفارش استفاده کنید."
            )
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
        if order.service == "image":
            # تصمیم پرداخت فقط برای سفارش ویدیو است؛ سفارش عکس مسیر خودش را دارد
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

    # ---------- پاسخ پشتیبانی: مدیر روی پیام کاربر ریپلای می‌کند ----------
    def _support_ticket_for_reply(message: Message):
        reply = message.reply_to_message
        if reply is None:
            return None
        ticket = store.get_support_by_admin_message(
            str(message.chat.id), str(reply.message_id)
        )
        if ticket is not None:
            return ticket
        # مسیر پشتیبان: کد پیگیری داخل متن/کپشن پیام ریپلای‌شده
        ref = sup.find_support_ref(" ".join(filter(None, [reply.text, reply.caption])))
        return store.get_support_message(ref) if ref else None

    def _admin_support_reply_filter(message: Message, **_kw) -> bool:
        return _is_admin(message) and _support_ticket_for_reply(message) is not None

    @dp.message(_admin_support_reply_filter)
    async def admin_support_reply(message: Message, bot: Bot) -> None:
        ticket = _support_ticket_for_reply(message)
        if ticket is None:
            return
        owner = store.get_user(ticket.user_key)
        target_chat = ticket.user_chat_id or (owner.chat_id if owner else None)
        if not target_chat:
            await message.answer("چت کاربر صاحب این پیام پشتیبانی پیدا نشد.")
            return
        try:
            target: object = int(target_chat)
        except (TypeError, ValueError):
            target = target_chat
        try:
            if message.photo:
                photo = max(message.photo, key=lambda p: (p.file_size or 0, p.width * p.height))
                await bot.send_photo(
                    chat_id=target,
                    photo=photo.file_id,
                    caption=(message.caption or sup.SUPPORT_REPLY_PREFIX),
                )
            elif message.video is not None:
                await bot.send_video(
                    chat_id=target,
                    video=message.video.file_id,
                    caption=(message.caption or sup.SUPPORT_REPLY_PREFIX),
                )
            elif message.text:
                await bot.send_message(
                    chat_id=target,
                    text=f"{sup.SUPPORT_REPLY_PREFIX}:\n\n{message.text}",
                )
            else:
                await message.answer("پاسخ پشتیبانی باید متن، عکس یا ویدیو باشد.")
                return
        except Exception:
            logger.exception("ارسال پاسخ پشتیبانی به کاربر ممکن نشد")
            await message.answer("ارسال پاسخ به کاربر ناموفق بود؛ دوباره تلاش کنید.")
            return
        await message.answer("✅ پاسخ شما برای کاربر ارسال شد.")

    def _admin_flow_filter(message: Message, **_kwargs) -> bool:
        uname = message.from_user.username if message.from_user else None
        if not is_admin_ids(_user_key(message), message.chat.id, uname):
            return False
        state = store.get_flow_state(_user_key(message))
        return state is not None and (
            state[0].startswith("admin_wait_delivery_photo")
            or state[0].startswith("admin_wait_delivery_video")
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
        if state.startswith("admin_wait_delivery_photo"):
            try:
                order_id = int(state.rsplit(":", 1)[1])
            except (ValueError, IndexError):
                store.clear_flow_state(key)
                return
            if not message.photo:
                await message.answer("لطفاً تصویر نهایی سفارش را ارسال کنید (عکس).")
                return
            order = store.get_order(order_id)
            target = store.get_user(order.user_key) if order else None
            if order is None or target is None or not target.chat_id:
                store.clear_flow_state(key)
                await message.answer("کاربر صاحب سفارش پیدا نشد؛ تحویل ممکن نیست.")
                return
            if order.service != "image" or order.status not in (
                STATUS_PENDING_REVIEW,
                STATUS_PROCESSING,
            ):
                # سفارش ردشده (یا تکمیل‌شده) نهایی است و دیگر تحویل داده نمی‌شود
                store.clear_flow_state(key)
                await message.answer("این سفارش تصویر رد یا تکمیل شده و دیگر قابل تحویل نیست.")
                return
            photo = max(message.photo, key=lambda p: (p.file_size or 0, p.width * p.height))
            try:
                await bot.send_photo(
                    chat_id=int(target.chat_id),
                    photo=photo.file_id,
                    caption=f"🖼 تصویر سفارش شما آماده شد!\nشماره سفارش: {order_id}",
                )
            except Exception:
                logger.exception("تحویل تصویر سفارش %s ممکن نشد", order_id)
                await message.answer("ارسال تصویر به کاربر ناموفق بود؛ دوباره تلاش کنید.")
                return
            saved = store.complete_image_delivery(order_id, photo.file_id)
            store.clear_flow_state(key)
            if saved is None or saved.status != STATUS_COMPLETED:
                await message.answer("وضعیت این سفارش قبلاً نهایی شده بود؛ تحویل ثبت نشد.")
                return
            await message.answer(f"✅ تصویر سفارش شماره {order_id} برای کاربر ارسال و سفارش تکمیل شد.")
            return
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
        # مدیر هم اگر خودش فرایند سفارش را شروع کرده، مثل کاربر ادامه می‌دهد؛
        # هندلرهای مدیریتی بالاتر زودتر اجرا می‌شوند و تداخلی پیش نمی‌آید.
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

    # ---------- ساخت تصویر و اعتبار رایگان ----------
    @dp.message(Text(text=texts.BTN_CREATE_IMAGE))
    async def start_image_order(message: Message, bot: Bot) -> None:
        ensure_user(message)
        store.ensure_daily_credit(_user_key(message))
        hero = Path(__file__).resolve().parent / "assets" / "image_hero.jpg"
        # عکس و متن معرفی و دکمه‌ها همه در یک پیام واحد (عکس با کپشن) می‌روند
        if hero.is_file():
            try:
                await bot.send_photo(
                    chat_id=message.chat.id,
                    photo=str(hero),
                    caption=io.IMAGE_INTRO_HTML,
                    parse_mode="HTML",
                    reply_markup=build_image_mode_keyboard(),
                )
                return
            except Exception:
                logger.exception("ارسال یکپارچه عکس و متن ساخت تصویر ممکن نشد؛ متن جدا می‌رود")
        await bot.send_message(
            chat_id=message.chat.id,
            text=io.IMAGE_INTRO_HTML,
            parse_mode="HTML",
            reply_markup=build_image_mode_keyboard(),
        )

    @dp.message(Text(text=texts.BTN_FREE_CREDIT))
    async def free_credit(message: Message, bot: Bot) -> None:
        user = ensure_user(message)
        balance = store.ensure_daily_credit(user.user_key)
        img = Path(__file__).resolve().parent / "assets" / "free_credit.jpg"
        text = io.balance_text(balance)
        if img.is_file():
            try:
                await bot.send_photo(chat_id=message.chat.id, photo=str(img), caption=text)
                return
            except Exception:
                logger.exception("ارسال تصویر اعتبار رایگان ممکن نشد؛ متن ارسال می‌شود")
        await message.answer(text, reply_markup=build_main_keyboard())

    # ---------- ارتباط با پشتیبانی / نمونه‌ها / گروه / کانال ----------
    async def _forward_support_message(
        bot: Bot,
        message: Message,
        body: str,
        photo_file_id: str | None = None,
    ) -> None:
        user = ensure_user(message)
        if not settings.admin_chat_id:
            store.clear_flow_state(user.user_key)
            await message.answer(sup.SUPPORT_UNAVAILABLE_TEXT, reply_markup=build_main_keyboard())
            return
        ticket = store.create_support_message(
            user.user_key,
            str(message.chat.id),
            str(settings.admin_chat_id),
            user_message_id=str(message.message_id),
        )
        try:
            if photo_file_id:
                sent = await bot.send_photo(
                    chat_id=settings.admin_chat_id,
                    photo=photo_file_id,
                    caption=sup.support_admin_caption(ticket.id, user, body),
                    parse_mode="HTML",
                )
            else:
                sent = await bot.send_message(
                    chat_id=settings.admin_chat_id,
                    text=sup.support_admin_text(ticket.id, user, body),
                    parse_mode="HTML",
                )
        except Exception:
            logger.exception("ارسال پیام پشتیبانی برای مدیر ممکن نشد")
            await message.answer(sup.SUPPORT_SEND_FAILED_TEXT)
            return
        admin_message_id = getattr(sent, "message_id", None)
        if admin_message_id is not None:
            store.set_support_admin_message(ticket.id, str(admin_message_id))
        store.clear_flow_state(user.user_key)
        await message.answer(sup.SUPPORT_SENT_TEXT, reply_markup=build_main_keyboard())

    @dp.message(Text(text=texts.BTN_SUPPORT))
    async def start_support(message: Message) -> None:
        ensure_user(message)
        if not settings.admin_chat_id:
            await message.answer(sup.SUPPORT_UNAVAILABLE_TEXT, reply_markup=build_main_keyboard())
            return
        store.set_flow_state(_user_key(message), "support_wait_message")
        await message.answer(sup.SUPPORT_PROMPT_TEXT)

    @dp.message(Text(text=texts.BTN_SAMPLES))
    async def samples(message: Message) -> None:
        await message.answer(texts.SAMPLES_TEXT, reply_markup=build_main_keyboard())

    @dp.message(Text(text=texts.BTN_GROUP))
    async def fox_group(message: Message, bot: Bot) -> None:
        ensure_user(message)
        url = settings.group_url or texts.FOX_GROUP_URL
        img = Path(__file__).resolve().parent / "assets" / "fox_group.jpg"
        if not img.is_file():
            img = Path(__file__).resolve().parent / "assets" / "image_hero.jpg"
        markup = build_group_keyboard(url)
        if img.is_file():
            try:
                await bot.send_photo(
                    chat_id=message.chat.id,
                    photo=str(img),
                    caption=texts.GROUP_CAPTION,
                    reply_markup=markup,
                )
                return
            except Exception:
                logger.exception("ارسال عکس گروه روباه ممکن نشد؛ فقط دکمه ارسال می‌شود")
        await bot.send_message(chat_id=message.chat.id, text=texts.GROUP_CAPTION, reply_markup=markup)

    @dp.message(Text(text=texts.BTN_CHANNEL))
    async def fox_channel(message: Message, bot: Bot) -> None:
        ensure_user(message)
        url = settings.channel_url or texts.FOX_CHANNEL_URL
        if url.startswith("@"):
            url = f"https://splus.ir/{url.lstrip('@')}"
        await bot.send_message(
            chat_id=message.chat.id,
            text=texts.CHANNEL_MAIN_TEXT,
            reply_markup=build_channel_keyboard(url),
        )

    def _support_flow_filter(message: Message, **_kw) -> bool:
        state = store.get_flow_state(_user_key(message))
        if state is None or state[0] != "support_wait_message":
            return False
        menu_texts = {t for row in texts.MENU_ROWS for t in row} | {
            texts.MENU_TEXT_COMMAND,
            "/start",
            "/menu",
        }
        return (message.text or "").strip() not in menu_texts

    @dp.message(_support_flow_filter)
    async def user_support_message(message: Message, bot: Bot) -> None:
        body = (message.text or "").strip()
        if not body:
            await message.answer(sup.SUPPORT_PROMPT_TEXT)
            return
        await _forward_support_message(bot, message, body)

    async def _submit_image_order(
        bot: Bot,
        chat_id: int,
        user_key: str,
        mode: str,
        model: str,
        prompt: str,
        photo_file_id: str | None,
    ) -> None:
        order = store.create_image_order(user_key, mode, model, prompt, photo_file_id)
        store.clear_flow_state(user_key)
        if order is None:
            await bot.send_message(chat_id=chat_id, text=io.NO_CREDIT_TEXT)
            return
        balance = store.ensure_daily_credit(user_key)
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"✅ سفارش تصویر شماره {order.id} ثبت و برای مدیریت ارسال شد.\n"
                f"هزینه: {order.credit_cost} اعتبار | موجودی شما: {balance} اعتبار\n"
                "تصویر نهایی پس از آماده شدن همین‌جا برایتان ارسال می‌شود."
            ),
            reply_markup=build_main_keyboard(),
        )
        await _notify_admin_image_order(bot, order)

    async def _notify_admin_image_order(bot: Bot, order) -> None:
        if not settings.admin_chat_id:
            logger.error(
                "ADMIN_CHAT_ID تنظیم نشده؛ سفارش تصویر %s در صف مدیر باقی ماند.", order.id
            )
            return
        user = store.get_user(order.user_key)
        balance = store.ensure_daily_credit(order.user_key)
        details = io.image_admin_html(order, user, balance)
        try:
            if order.request_photo_file_id:
                await bot.send_photo(
                    chat_id=settings.admin_chat_id,
                    photo=order.request_photo_file_id,
                    caption=details[:1000],
                    parse_mode="HTML",
                    reply_markup=build_image_admin_keyboard(order.id),
                )
            else:
                await bot.send_message(
                    chat_id=settings.admin_chat_id,
                    text=details,
                    parse_mode="HTML",
                    reply_markup=build_image_admin_keyboard(order.id),
                )
        except Exception:
            logger.exception("ارسال سفارش تصویر %s برای مدیر ممکن نشد", order.id)

    def _img_prompt_filter(message: Message, **_kw) -> bool:
        # مهم: مدیر (صاحب ربات) هم وقتی «ساخت تصویر» را شروع کرده باید بتواند
        # پرامپت بفرستد؛ حذف این استثنا علت گیرکردن مرحله پرامپت برای مدیر بود.
        state = store.get_flow_state(_user_key(message))
        return state is not None and state[0] == "img_wait_prompt"

    @dp.message(_img_prompt_filter)
    async def user_image_prompt(message: Message, bot: Bot) -> None:
        key = _user_key(message)
        _state, payload = store.get_flow_state(key) or ("", None)
        mode, _, model = (payload or "").partition("|")
        text = (message.text or "").strip()
        if text in (texts.MENU_TEXT_COMMAND, "/start", "/menu", "لغو"):
            store.clear_flow_state(key)
            await _answer(message)
            return
        if not text or mode not in io.IMAGE_MODES or not model:
            await message.answer(io.IMAGE_PROMPT_TEXT)
            return
        await _submit_image_order(bot, message.chat.id, key, mode, model, text, None)

    # ---------- ساخت ویدیو و سفارش‌های من ----------
    @dp.message(Text(text=texts.BTN_CREATE_VIDEO))
    async def start_video_order(message: Message, bot: Bot) -> None:
        ensure_user(message)
        store.create_or_get_draft(_user_key(message))

        async def _send_intro() -> None:
            await bot.send_message(
                chat_id=message.chat.id,
                text=vo.VIDEO_INTRO_HTML,
                parse_mode="HTML",
                reply_markup=build_order_type_keyboard(),
            )

        # ویدیوی پیش‌فرض مدیر (اگر تنظیم و فعال باشد) هم‌زمان با پیام و
        # دکمه‌های شروع می‌رود تا کاربر برای دیدن دکمه‌ها منتظر ویدیو نماند.
        default_file = None
        default_caption = None
        if store.get_setting(vo.DEFAULT_VIDEO_ENABLED_KEY) == "1":
            default_file = store.get_setting(vo.DEFAULT_VIDEO_FILE_KEY)
            default_caption = store.get_setting(vo.DEFAULT_VIDEO_TEXT_KEY)
        if default_file:
            async def _send_default_video() -> None:
                try:
                    await bot.send_video(
                        chat_id=message.chat.id, video=default_file, caption=default_caption
                    )
                except Exception:
                    logger.exception("ارسال ویدیوی پیش‌فرض ممکن نشد؛ فرایند سفارش ادامه می‌یابد")

            await asyncio.gather(_send_default_video(), _send_intro())
        else:
            await _send_intro()

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
        if flow is not None and flow[0] == "support_wait_message":
            # پیام پشتیبانیِ تصویری: عکس (با توضیحش اگر باشد) برای مدیر می‌رود
            photo = max(message.photo, key=lambda p: (p.file_size or 0, p.width * p.height))
            await _forward_support_message(
                bot, message, (message.caption or "").strip(), photo_file_id=photo.file_id
            )
            return
        if flow is not None and flow[0] == "img_wait_photo":
            mode, _, model = (flow[1] or "").partition("|")
            caption = (message.caption or "").strip()
            if not caption:
                await message.answer(
                    "عکس باید متن توضیحی داشته باشد؛ عکس را با توضیح در کپشن دوباره ارسال کنید."
                )
                return
            photo = max(message.photo, key=lambda p: (p.file_size or 0, p.width * p.height))
            if mode not in io.IMAGE_MODES or not model:
                store.clear_flow_state(_user_key(message))
                await message.answer("از «ساخت تصویر» دوباره شروع کنید.", reply_markup=build_main_keyboard())
                return
            await _submit_image_order(
                bot, message.chat.id, _user_key(message), mode, model, caption, photo.file_id
            )
            return
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
            # جزئیات سفارش فقط یک بار و همراه خودِ رسید ارسال می‌شود (کپشن عکس)
            await bot.send_photo(
                chat_id=settings.admin_chat_id,
                photo=order.receipt_file_id,
                caption=vo.order_admin_caption(order, user),
                parse_mode="HTML",
                reply_markup=build_admin_order_keyboard(order.id),
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

    def _cb_rules_blocked(callback: CallbackQuery, **_kw) -> bool:
        if callback.data == "rules:accept":
            return False
        return not store.has_accepted_rules(_cb_user_key(callback))

    @dp.callback_query(_cb_rules_blocked)
    async def rules_callback_guard(callback: CallbackQuery, bot: Bot) -> None:
        await _cb_answer(bot, callback, texts.RULES_REQUIRED_TEXT, alert=True)

    @dp.callback_query(Text(startswith="rules:"))
    async def on_rules_accept(callback: CallbackQuery, bot: Bot) -> None:
        chat_id = callback.message.chat.id if callback.message else None
        if callback.data != "rules:accept" or chat_id is None:
            await _cb_answer(bot, callback, "گزینه نامعتبر است.", alert=True)
            return
        user_key = _cb_user_key(callback)
        store.get_or_create_user(
            user_key,
            chat_id=str(chat_id),
            username=callback.from_user.username,
            display_name=getattr(callback.from_user, "full_name", None),
        )
        store.set_rules_accepted(user_key, True)
        await _cb_answer(bot, callback, "قوانین تأیید شد ✅")
        # تازه بعد از تأیید قوانین، منوی اصلی برای کاربر باز می‌شود
        await bot.send_message(
            chat_id=chat_id,
            text=texts.WELCOME_TEXT,
            reply_markup=build_main_keyboard(),
        )

    @dp.callback_query(Text(startswith="it:"))
    async def on_image_mode_chosen(callback: CallbackQuery, bot: Bot) -> None:
        mode = callback.data.split(":", 1)[1] if callback.data else ""
        chat_id = callback.message.chat.id if callback.message else None
        if mode not in io.IMAGE_MODES or chat_id is None:
            await _cb_answer(bot, callback, "گزینه نامعتبر است.", alert=True)
            return
        user_key = _cb_user_key(callback)
        store.get_or_create_user(
            user_key,
            chat_id=str(chat_id),
            username=callback.from_user.username,
            display_name=getattr(callback.from_user, "full_name", None),
        )
        store.set_flow_state(user_key, "img_wait_model", mode)
        await _cb_answer(bot, callback, f"«{io.IMAGE_MODES[mode]}» انتخاب شد.")
        await bot.send_message(
            chat_id=chat_id,
            text="مدل ساخت تصویر را انتخاب کنید:",
            reply_markup=build_image_model_keyboard(),
        )

    @dp.callback_query(Text(startswith="im:"))
    async def on_image_model_chosen(callback: CallbackQuery, bot: Bot) -> None:
        chat_id = callback.message.chat.id if callback.message else None
        try:
            model = io.IMAGE_MODELS[int(callback.data.split(":", 1)[1])]
        except (ValueError, IndexError):
            model = ""
        user_key = _cb_user_key(callback)
        flow = store.get_flow_state(user_key)
        mode = flow[1] if flow and flow[0] == "img_wait_model" else None
        if chat_id is None or not model or mode not in io.IMAGE_MODES:
            await _cb_answer(bot, callback, "اول از «ساخت تصویر» نحوه تولید را انتخاب کنید.", alert=True)
            return
        await _cb_answer(bot, callback, f"مدل {model} انتخاب شد.")
        if mode == "gen":
            store.set_flow_state(user_key, "img_wait_prompt", f"{mode}|{model}")
            await bot.send_message(chat_id=chat_id, text=io.IMAGE_PROMPT_TEXT)
        else:
            store.set_flow_state(user_key, "img_wait_photo", f"{mode}|{model}")
            await bot.send_message(chat_id=chat_id, text=io.IMAGE_PHOTO_PROMPT_TEXT)

    @dp.callback_query(Text(startswith="idl:"))
    async def on_image_deliver_clicked(callback: CallbackQuery, bot: Bot) -> None:
        chat_id = callback.message.chat.id if callback.message else 0
        if not is_admin_ids(_cb_user_key(callback), chat_id, callback.from_user.username):
            await _cb_answer(bot, callback, vo.NOT_ADMIN_TEXT, alert=True)
            return
        try:
            order_id = int(callback.data.split(":", 1)[1])
        except (ValueError, IndexError):
            order_id = -1
        order = store.get_order(order_id)
        if order is None or order.service != "image" or order.status not in (
            STATUS_PENDING_REVIEW,
            STATUS_PROCESSING,
        ):
            await _cb_answer(bot, callback, "این سفارش تصویر آماده تحویل نیست.", alert=True)
            return
        store.update_status(order_id, STATUS_PROCESSING)
        store.set_flow_state(
            _cb_user_key(callback), f"admin_wait_delivery_photo:{order_id}"
        )
        await _cb_answer(bot, callback)
        await bot.send_message(
            chat_id=chat_id,
            text=f"🖼 تصویر نهایی سفارش شماره {order_id} را ارسال کنید تا برای کاربر فرستاده شود.",
        )

    @dp.callback_query(Text(startswith="irj:"))
    async def on_image_reject_clicked(callback: CallbackQuery, bot: Bot) -> None:
        chat_id = callback.message.chat.id if callback.message else 0
        if not is_admin_ids(_cb_user_key(callback), chat_id, callback.from_user.username):
            await _cb_answer(bot, callback, vo.NOT_ADMIN_TEXT, alert=True)
            return
        try:
            order_id = int(callback.data.split(":", 1)[1])
        except (ValueError, IndexError):
            order_id = -1
        order = store.get_order(order_id)
        if order is None or order.service != "image" or order.status not in (
            STATUS_PENDING_REVIEW,
            STATUS_PROCESSING,
        ):
            await _cb_answer(bot, callback, "این سفارش قبلاً بررسی شده است.", alert=True)
            return
        # رد نهایی و کامل: وضعیت rejected می‌شود، اعتبار برمی‌گردد و اگر مدیر
        # وسط تحویل بوده، آن حالت هم پاک می‌شود تا بعداً قابل تحویل نباشد.
        store.update_status(order_id, STATUS_REJECTED)
        balance = store.add_credit(order.user_key, order.credit_cost)
        admin_key = _cb_user_key(callback)
        flow = store.get_flow_state(admin_key)
        if flow is not None and flow[0] == f"admin_wait_delivery_photo:{order_id}":
            store.clear_flow_state(admin_key)
        await _cb_answer(bot, callback, "سفارش تصویر رد و اعتبار برگردانده شد ❌")
        owner = store.get_user(order.user_key)
        if owner and owner.chat_id:
            try:
                await bot.send_message(
                    chat_id=int(owner.chat_id),
                    text=(
                        f"❌ سفارش تصویر شماره {order_id} رد شد.\n"
                        f"{order.credit_cost} اعتبار به شما برگردانده شد. موجودی فعلی: {balance}"
                    ),
                )
            except Exception:
                logger.exception("اطلاع رد سفارش تصویر به کاربر ممکن نشد")

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
        prompt = vo.ORDER_TEXT_PROMPT if kind == "text" else vo.ORDER_PHOTO_PROMPT
        # پاسخ کال‌بک و پیام مرحله بعد هم‌زمان می‌روند تا زمان کلیک نصف شود
        await asyncio.gather(
            _cb_answer(bot, callback, f"«{vo.ORDER_TYPES[kind]}» انتخاب شد."),
            bot.send_message(chat_id=chat_id, text=prompt),
        )

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
        await asyncio.gather(
            _cb_answer(bot, callback, f"مدل {model} انتخاب شد."),
            bot.send_message(
                chat_id=chat_id,
                text=f"✅ مدل «{model}» برای سفارش شماره {order.id} انتخاب شد.\n"
                "حالا مدت ویدیو را انتخاب کنید:",
                reply_markup=build_duration_keyboard(),
            ),
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
        await asyncio.gather(
            _cb_answer(bot, callback, "مدت و مبلغ ثبت شد."),
            _send_payment(bot, chat_id, order),
        )

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
                await _send_local_photo_cached(
                    bot,
                    chat_id,
                    Path(guide),
                    "payment_guide",
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
        await asyncio.gather(
            _cb_answer(bot, callback),
            bot.send_message(chat_id=chat_id, text=vo.RECEIPT_PROMPT_TEXT),
        )

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
        if order.service == "image":
            await _cb_answer(
                bot,
                callback,
                "این سفارش تصویر است؛ از دکمه‌های روی پیام سفارش تصویر استفاده کنید.",
                alert=True,
            )
            return
        await _apply_admin_decision(bot, order_id, approve, admin_chat_id=chat_id)
        await _cb_answer(bot, callback, "پرداخت تأیید شد ✅" if approve else "پرداخت رد شد ❌")

    # ---------- fallback ----------
    # «نمونه‌ها»، «ارتباط با پشتیبانی»، «گروه روباه» و «کانال روباه» بالاتر
    # هندلر اختصاصی دارند و دیگر به‌صورت متن ثابت پاسخ داده نمی‌شوند.
    # متن/فایل غیرعکس در حالی که ربات منتظر تصویر رسید این کاربر است
    @dp.message(_has_receipt_candidate)
    async def on_invalid_receipt_content(message: Message) -> None:
        await message.answer(vo.RECEIPT_INVALID_TEXT)

    @dp.message()
    async def fallback(message: Message) -> None:
        logger.info("پیام ناشناخته دریافت شد (chat_id=%s)", message.chat.id)
        await _answer(message)

    return dp
