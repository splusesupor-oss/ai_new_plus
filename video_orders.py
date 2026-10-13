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

DEFAULT_VIDEO_FILE_KEY = "default_video_file_id"
DEFAULT_VIDEO_TEXT_KEY = "default_video_text"
DEFAULT_VIDEO_ENABLED_KEY = "default_video_enabled"

VIDEO_INTRO_PLAIN = (
    "🎥 ساخت ویدیو با مدل هوش مصنوعی روباه\n"
    "\n"
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


def user_orders_text(orders: list[Order], user: UserRecord) -> str:
    """متن دکمه «سفارش‌های من» برای خود کاربر."""
    header = f"📦 سفارش‌های من\nشناسه کاربری شما: {user.code}\n"
    if not orders:
        return header + "\nهنوز سفارشی ثبت نکرده‌اید. از منوی اصلی «ساخت ویدیو» را انتخاب کنید."
    lines = [header]
    for order in orders:
        lines.append(
            "\n"
            f"🧾 سفارش شماره {order.id}\n"
            f"مدل: {order.model or '—'} | مدت: {duration_label(order.duration_seconds)}\n"
            f"مبلغ: {format_amount(order.amount_toman)}\n"
            f"وضعیت: {STATUS_LABELS.get(order.status, order.status)}\n"
            f"تاریخ: {order.created_at}"
        )
    return "\n".join(lines)
