# -*- coding: utf-8 -*-
"""منطق بخش «ساخت تصویر» و اعتبار رایگان روزانه.

هر سفارش تصویر (تولید/ویرایش/تغییر چهره) ۱۰ اعتبار از ۵۰ اعتبار
رایگان روزانه کم می‌کند. پرداخت و تأیید پرداخت ندارد؛ سفارش مستقیم
برای مدیر می‌رود و مدیر تصویر نهایی را تحویل می‌دهد یا رد می‌کند
(با رد شدن، اعتبار به کاربر برمی‌گردد).
"""
from __future__ import annotations

import html

from storage import (
    STATUS_COMPLETED,
    STATUS_PAYMENT_APPROVED,
    STATUS_PENDING_REVIEW,
    STATUS_PROCESSING,
    STATUS_REJECTED,
    Order,
    UserRecord,
)
from video_orders import user_display

IMAGE_INTRO_PLAIN = (
    "🖼 سفارش تصویر با هوش مصنوعی روباه\n"
    "\n"
    "← نحوه تولید را انتخاب کنید\n"
    "← مدل را انتخاب کنید\n"
    "← متن خودتون رو ارسال کنید\n"
    "← منتظر دریافت سفارش باشید"
)
IMAGE_INTRO_HTML = f"<b>{html.escape(IMAGE_INTRO_PLAIN)}</b>"

# حالت ساخت: کلید -> عنوان دقیق دکمه
IMAGE_MODES = {
    "gen": "تولید تصویر",
    "edit": "ویرایش تصویر",
    "face": "تغییر چهره",
}

# مدل‌های تصویر (عنوان دقیق دکمه‌ها)
IMAGE_MODELS = ["GPT 6", "flash pro 3", "nano banana pro", "fox plus 6"]

IMAGE_COST = 10
DAILY_CREDIT = 50

FREE_CREDIT_TEXT = "شما 50 اعتبار رایگان برای ساخت 5 عکس دریافت کردید"
IMAGE_PROMPT_TEXT = "✍️ پرامپت (متن) تصویر موردنظرتان را بنویسید و ارسال کنید:"
IMAGE_PHOTO_PROMPT_TEXT = (
    "🖼 عکس موردنظرتان را همراه با متن توضیحی (در کپشن عکس) ارسال کنید:\n"
    "عکس بدون متن ثبت نمی‌شود."
)
NO_CREDIT_TEXT = (
    "⛔ اعتبار رایگان امروزتان تمام شده است.\n"
    "اعتبار هر شب ساعت ۱۲ شب به وقت تهران دوباره ۵۰ می‌شود."
)
DELIVER_IMAGE_BUTTON_TEXT = "🎨 ارسال تصویر نهایی"
REJECT_IMAGE_BUTTON_TEXT = "❌ رد سفارش"

# برچسب وضعیت مخصوص سفارش عکس؛ سفارش عکس پرداخت ندارد و نباید برای آن
# «در انتظار پرداخت/بررسی پرداخت» نمایش داده شود.
IMAGE_STATUS_LABELS = {
    STATUS_PENDING_REVIEW: "در انتظار ارسال عکس",
    STATUS_PROCESSING: "در انتظار ارسال عکس",
    STATUS_PAYMENT_APPROVED: "در انتظار ارسال عکس",
    STATUS_COMPLETED: "تکمیل شده",
    STATUS_REJECTED: "رد شد",
}


def image_status_label(status: str) -> str:
    return IMAGE_STATUS_LABELS.get(status, "در انتظار ارسال عکس")


def balance_text(balance: int) -> str:
    return (
        f"{FREE_CREDIT_TEXT}\n"
        f"موجودی فعلی شما: {balance} اعتبار "
        f"(هر سفارش تصویر {IMAGE_COST} اعتبار)"
    )


def image_admin_html(order: Order, user: UserRecord | None, balance: int | None = None) -> str:
    """جزئیات سفارش تصویر برای مدیر با عنوان‌های Bold."""
    balance_line = (
        f"\n<b>اعتبار باقی‌مانده کاربر:</b> {balance}" if balance is not None else ""
    )
    return (
        f"<b>🖼 سفارش تصویر شماره {order.id}</b>\n"
        f"<b>نوع:</b> {html.escape(IMAGE_MODES.get(order.image_mode or '', '—'))}\n"
        f"<b>مدل:</b> {html.escape(order.model or '—')}\n"
        f"<b>متن کاربر:</b>\n{html.escape(order.request_text or '—')}\n"
        f"<b>کاربر:</b> {html.escape(user_display(user))}\n"
        f"<b>شناسه شش‌رقمی:</b> {html.escape(user.code if user else '—')}\n"
        f"<b>شناسه سروش‌پلاس:</b> {html.escape(order.user_key)}\n"
        f"<b>هزینه:</b> {order.credit_cost} اعتبار\n"
        f"<b>وضعیت:</b> {html.escape(image_status_label(order.status))}"
        f"{balance_line}\n"
        f"<b>تاریخ:</b> {html.escape(order.created_at)}"
    )
