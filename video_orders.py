# -*- coding: utf-8 -*-
"""منطق و متن‌های بخش «ساخت ویدیو» و سفارش‌های آن.

مدل‌ها در این مرحله فقط گزینه‌های انتخابی‌اند؛ هیچ API تولید ویدیویی
متصل نیست و ربات ادعا نمی‌کند ویدیو به‌صورت خودکار تولید می‌شود.
مبالغ و مدت‌ها فقط از همین جدول خوانده می‌شوند.
"""
from __future__ import annotations

import html

from config import Settings
from storage import (
    STATUS_AWAITING_RECEIPT,
    STATUS_COMPLETED,
    STATUS_DRAFT,
    STATUS_PAYMENT_APPROVED,
    STATUS_PENDING_REVIEW,
    STATUS_PROCESSING,
    STATUS_REJECTED,
    Order,
    UserRecord,
)

# مدل‌های ویدیوساز: کلید callback -> عنوان دقیق دکمه
MODELS = {
    "mplus": "model plus",
    "mfox": "model fox",
    "macod": "model acod",
}

# مدت (ثانیه) -> مبلغ دقیق (تومان)
DURATIONS = {
    10: 35_000,
    20: 60_000,
    30: 80_000,
}

STATUS_LABELS = {
    STATUS_DRAFT: "پیش‌نویس (ناتمام)",
    STATUS_AWAITING_RECEIPT: "در انتظار ارسال رسید",
    STATUS_PENDING_REVIEW: "در انتظار بررسی پرداخت",
    STATUS_PAYMENT_APPROVED: "پرداخت تأیید شده",
    STATUS_PROCESSING: "در حال انجام سفارش",
    STATUS_COMPLETED: "تکمیل شده",
    STATUS_REJECTED: "رد شده",
}

ADMIN_SET_VIDEO_COMMAND = "تنظیم ویدیو"
ADMIN_DELETE_VIDEO_COMMAND = "حذف ویدیو"
ADMIN_SET_VIDEO_TEXT_COMMAND = "تنظیم متن ویدیو"
ADMIN_PENDING_COMMAND = "سفارش‌های در انتظار"
ADMIN_MEMBERS_COMMAND = "اعضا"
ADMIN_BROADCAST_COMMAND = "اطلاع رسانی"
ADMIN_READY_COMMAND = "تحویل سفارش‌ها"

# نوع سفارش: کلید -> عنوان دکمه و برچسب نمایشی
ORDER_TYPES = {
    "text": "ساخت ویدیو با متن",
    "photo": "ساخت ویدیو با عکس",
}
MIN_ORDER_TEXT_LENGTH = 100

TYPE_BUTTON_TEXT = "نوع ساخت ویدیو را انتخاب کنید:"
ORDER_TEXT_PROMPT = (
    "✍️ متن موردنظرتان برای ساخت ویدیو را ارسال کنید.\n"
    f"متن باید حداقل {MIN_ORDER_TEXT_LENGTH} کاراکتر باشد."
)
ORDER_PHOTO_PROMPT = (
    "🖼 عکس موردنظرتان را همراه با یک متن توضیحی (در کپشن عکس) ارسال کنید.\n"
    "عکس بدون متن توضیحی ثبت نمی‌شود."
)
BLOCKED_TEXT = "⛔ حساب شما توسط مدیریت مسدود شده است و امکان استفاده از ربات را ندارید."
DELIVER_BUTTON_TEXT = "🎬 ارسال ویدیو"
BROADCAST_CONFIRM_TEXT = "✅ تأیید ارسال"
BROADCAST_CANCEL_TEXT = "❌ لغو"

DEFAULT_VIDEO_FILE_KEY = "default_video_file_id"
DEFAULT_VIDEO_TEXT_KEY = "default_video_text"
DEFAULT_VIDEO_ENABLED_KEY = "default_video_enabled"

VIDEO_INTRO_PLAIN = (
    "🎥 ساخت ویدیو با مدل هوش مصنوعی روباه\n"
    "\n"
    "● نوع سفارش (با متن یا با عکس) را انتخاب کنید\n"
    "● مدل را انتخاب کنید\n"
    "● تایم ویدیو را انتخاب کنید\n"
    "● هزینه را پرداخت و رسید را ارسال کنید\n"
    "● منتظر دریافت سفارش در کمترین زمان باشید"
)

# تمام متن معرفی باید Bold باشد؛ با HTML سازگار با Bot API سروش‌پلاس
VIDEO_INTRO_HTML = f"<b>{html.escape(VIDEO_INTRO_PLAIN)}</b>"

RECEIPT_BUTTON_TEXT = "📤 ارسال رسید"
RECEIPT_PROMPT_TEXT = (
    "📤 لطفاً تصویر رسید پرداخت را ارسال کنید.\n"
    "رسید باید عکس باشد؛ متن یا فایل دیگری قابل قبول نیست."
)
RECEIPT_INVALID_TEXT = (
    "⚠️ رسید معتبر نیست. لطفاً فقط تصویر (عکس) رسید پرداخت را ارسال کنید.\n"
    "اگر هنوز پرداخت نکرده‌اید، از مرحله پرداخت روی «📤 ارسال رسید» بزنید."
)
RECEIPT_RECEIVED_TEXT = (
    "✅ رسید شما دریافت شد و سفارش در وضعیت «در انتظار بررسی پرداخت» ثبت شد.\n"
    "پس از تأیید مدیر، نتیجه از همین‌جا اطلاع‌رسانی می‌شود."
)
RECEIPT_DUPLICATE_TEXT = "رسید این سفارش قبلاً ثبت شده و در انتظار بررسی است."
PAYMENT_NOT_CONFIGURED_TEXT = (
    "💳 اطلاعات پرداخت هنوز توسط مدیر تنظیم نشده است.\n"
    "لطفاً بعداً دوباره تلاش کنید یا با پشتیبانی در ارتباط باشید."
)
NOT_ADMIN_TEXT = "⛔ این دستور فقط برای مدیر ربات است."
ADMIN_NOT_CONFIGURED_TEXT = (
    "⚠️ مدیر ربات هنوز تنظیم نشده است (ADMIN_CHAT_ID در فایل .env خالی است)."
)


def fa_digits(value: int | str) -> str:
    """عدد لاتین را به رقم فارسی تبدیل می‌کند."""
    return str(value).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def format_amount(amount_toman: int | None) -> str:
    if amount_toman is None:
        return "—"
    return f"{fa_digits(f'{amount_toman:,}')} تومان"


def duration_label(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    return f"{fa_digits(seconds)} ثانیه"


def duration_button_text(seconds: int) -> str:
    """عنوان دقیق دکمه مدت، مثل: ۱۰ ثانیه — ۳۵ هزار تومان"""
    thousands = DURATIONS[seconds] // 1000
    return f"{fa_digits(seconds)} ثانیه — {fa_digits(thousands)} هزار تومان"


def build_payment_text(order: Order, settings: Settings) -> str | None:
    """متن پرداخت (HTML/Bold). اگر کارت تنظیم نشده باشد None برمی‌گرداند."""
    if not settings.payment_card_number or not settings.payment_card_holder:
        return None
    card = html.escape(settings.payment_card_number)
    holder = html.escape(settings.payment_card_holder)
    return (
        "<b>💳 اطلاعات پرداخت سفارش ویدیو</b>\n"
        "\n"
        f"شماره کارت:\n<code>{card}</code>\n"
        f"به نام: <b>{holder}</b>\n"
        f"مبلغ قابل پرداخت: <b>{format_amount(order.amount_toman)}</b>\n"
        f"مدل: <b>{html.escape(order.model or '—')}</b> | "
        f"مدت: <b>{duration_label(order.duration_seconds)}</b>\n"
        "\n"
        "<b>هزینه را به شماره کارت بالا پرداخت کنید و رسید را ارسال کنید.</b>"
    )


def order_summary(order: Order, user: UserRecord | None) -> str:
    """خلاصه کامل سفارش برای مدیر و کاربر (بدون هیچ شناسه جعلی)."""
    code = user.code if user else "—"
    splus_id = order.user_key
    return (
        f"🧾 سفارش شماره {order.id}\n"
        f"شناسه شش‌رقمی کاربر: {code}\n"
        f"شناسه حساب سروش‌پلاس کاربر: {splus_id}\n"
        f"مدل: {order.model or '—'}\n"
        f"مدت ویدیو: {duration_label(order.duration_seconds)}\n"
        f"مبلغ: {format_amount(order.amount_toman)}\n"
        f"وضعیت: {STATUS_LABELS.get(order.status, order.status)}\n"
        f"تاریخ ثبت: {order.created_at}"
    )


def user_display(user: UserRecord | None) -> str:
    """نام کاربر برای مدیر: اول یوزرنیم، اگر نداشت نام نمایشی."""
    if user is None:
        return "—"
    if user.username:
        return f"@{user.username.lstrip('@')}"
    return user.display_name or user.first_name or "—"


def order_type_label(order: Order) -> str:
    return ORDER_TYPES.get(order.order_type or "", "—")


def order_admin_html(order: Order, user: UserRecord | None, full_text: bool = True) -> str:
    """جزئیات کامل سفارش برای مدیر با عنوان‌های Bold (HTML سازگار با API)."""
    request_text = html.escape(order.request_text or "—")
    if not full_text and len(request_text) > 350:
        request_text = request_text[:350] + "…"
    return (
        f"<b>🧾 سفارش ویدیو شماره {order.id}</b>\n"
        f"<b>نوع سفارش:</b> {html.escape(order_type_label(order))}\n"
        f"<b>متن درخواست کاربر:</b>\n{request_text}\n"
        f"<b>کاربر:</b> {html.escape(user_display(user))}\n"
        f"<b>شناسه شش‌رقمی:</b> {html.escape(user.code if user else '—')}\n"
        f"<b>شناسه حساب سروش‌پلاس:</b> {html.escape(order.user_key)}\n"
        f"<b>مدل انتخابی:</b> {html.escape(order.model or '—')}\n"
        f"<b>مدت ویدیو:</b> {duration_label(order.duration_seconds)}\n"
        f"<b>مبلغ:</b> {format_amount(order.amount_toman)}\n"
        f"<b>وضعیت:</b> {html.escape(STATUS_LABELS.get(order.status, order.status))}\n"
        f"<b>تاریخ ثبت:</b> {html.escape(order.created_at)}"
    )


def order_admin_caption(order: Order, user: UserRecord | None) -> str:
    """جزئیات سفارش در همان کپشنِ عکس رسید (فقط یک پیام برای مدیر).

    متن درخواست اگر خیلی بلند باشد کوتاه می‌شود تا کل جزئیات داخل
    سقف کپشن عکس جا شود؛ متن کامل در دیتابیس ربات هست.
    """
    from dataclasses import replace

    text = order.request_text or ""
    if len(text) > 380:
        text = text[:380] + "…"
    return order_admin_html(replace(order, request_text=text), user, full_text=True)


def broadcast_to_html(raw: str) -> str:
    """تبدیل متن مدیر به HTML امن؛ بخش‌های **...** به Bold تبدیل می‌شوند.

    مثال ورودی مدیر: سلام **اطلاعیه مهم** برای همه
    """
    import re

    escaped = html.escape(raw.strip())
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped, flags=re.S)


def members_text(users: list[UserRecord]) -> str:
    """متن دستور «اعضا» برای مدیر: تعداد کل + اطلاعات هر عضو."""
    lines = [f"👥 اعضای ربات — تعداد کل: {len(users)} نفر\n"]
    for u in users:
        name = u.display_name or u.first_name or "—"
        username = f"@{u.username.lstrip('@')}" if u.username else "بدون یوزرنیم"
        blocked = " | 🚫 مسدود" if u.is_blocked else ""
        lines.append(
            f"\n<b>{html.escape(u.code)}</b> — {html.escape(name)} ({html.escape(username)})\n"
            f"شناسه سروش‌پلاس: {html.escape(u.user_key)} | چت: {html.escape(u.chat_id or '—')}"
            f"{blocked}\nشروع: {html.escape(u.created_at)}"
        )
    return "\n".join(lines)


def user_orders_text(orders: list[Order], user: UserRecord) -> str:
    """متن دکمه «سفارش‌های من» برای خود کاربر."""
    header = f"📦 سفارش‌های من\nشناسه کاربری شما: {user.code}\n"
    if not orders:
        return header + "\nهنوز سفارشی ثبت نکرده‌اید. از منوی اصلی «ساخت ویدیو» را انتخاب کنید."
    lines = [header]
    for order in orders:
        if getattr(order, "service", "video") == "image":
            from image_orders import IMAGE_MODES, image_status_label

            lines.append(
                "\n"
                f"🖼 سفارش تصویر شماره {order.id}\n"
                f"نوع: {IMAGE_MODES.get(order.image_mode or '', '—')} | مدل: {order.model or '—'}\n"
                f"هزینه: {order.credit_cost} اعتبار\n"
                f"وضعیت: {image_status_label(order.status)}\n"
                f"تاریخ: {order.created_at}"
            )
        else:
            lines.append(
                "\n"
                f"🧾 سفارش شماره {order.id}\n"
                f"مدل: {order.model or '—'} | مدت: {duration_label(order.duration_seconds)}\n"
                f"مبلغ: {format_amount(order.amount_toman)}\n"
                f"وضعیت: {STATUS_LABELS.get(order.status, order.status)}\n"
                f"تاریخ: {order.created_at}"
            )
    return "\n".join(lines)
