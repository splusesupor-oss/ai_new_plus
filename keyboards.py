# -*- coding: utf-8 -*-
"""ساخت کیبورد اصلی ربات.

از ReplyKeyboardMarkup رسمی Bot API سروش‌پلاس استفاده می‌شود؛ یعنی
دکمه‌ها زیر کادر پیام کاربر نمایش داده می‌شوند (نه Inline و نه متن ساده).
با فشردن هر دکمه، متن همان دکمه به‌عنوان پیام برای ربات ارسال می‌شود.

نکته برندینگ: Bot API سروش‌پلاس امکان تعیین رنگ واقعی دکمه‌های
Reply Keyboard را نمی‌دهد، پس رنگ نارنجی به دکمه‌ها نسبت داده نمی‌شود؛
حس بصری برند «روباه» با ایموجی 🦊 و قالب‌بندی پیام‌ها ایجاد می‌شود.
"""
from __future__ import annotations

from typing import Any

from aiosplus.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

import video_orders
from texts import MENU_ROWS

INPUT_PLACEHOLDER = "سرویس موردنظر را انتخاب کنید"


def build_main_keyboard() -> ReplyKeyboardMarkup:
    """کیبورد اصلی: ۴ ردیف × ۲ دکمه، با عنوان‌های دقیق تعریف‌شده در texts.py."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=title) for title in row] for row in MENU_ROWS
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder=INPUT_PLACEHOLDER,
    )


def keyboard_to_dict(keyboard: ReplyKeyboardMarkup) -> dict[str, Any]:
    """نمایش دیکشنری کیبورد، دقیقاً به همان شکلی که برای API ارسال می‌شود."""
    return keyboard.model_dump(exclude_none=True, by_alias=True)


# ---------- دکمه‌های شیشه‌ای (Inline Keyboard) بخش ساخت ویدیو ----------
# این‌ها InlineKeyboardMarkup واقعی Bot API سروش‌پلاس‌اند و روی همان پیام
# نمایش داده می‌شوند؛ با کلیک، callback_data برای ربات ارسال می‌شود.

def build_model_keyboard() -> InlineKeyboardMarkup:
    """مرحله ۱: سه مدل ویدیوساز، هرکدام یک دکمه مستقل."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=title, callback_data=f"vm:{key}")]
            for key, title in video_orders.MODELS.items()
        ]
    )


def build_duration_keyboard() -> InlineKeyboardMarkup:
    """مرحله ۲: مدت و قیمت دقیق."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=video_orders.duration_button_text(seconds),
                    callback_data=f"vd:{seconds}",
                )
            ]
            for seconds in video_orders.DURATIONS
        ]
    )


def build_receipt_keyboard(order_id: int) -> InlineKeyboardMarkup:
    """مرحله ۳: دکمه ارسال رسید برای همان سفارش."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=video_orders.RECEIPT_BUTTON_TEXT,
                    callback_data=f"vr:{order_id}",
                )
            ]
        ]
    )


def build_admin_order_keyboard(order_id: int) -> InlineKeyboardMarkup:
    """دکمه‌های مدیر روی پیام رسید: تأیید یا رد پرداخت همان سفارش."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ تأیید پرداخت", callback_data=f"va:{order_id}"),
                InlineKeyboardButton(text="❌ رد پرداخت", callback_data=f"vrj:{order_id}"),
            ]
        ]
    )


def inline_to_dict(keyboard: InlineKeyboardMarkup) -> dict[str, Any]:
    return keyboard.model_dump(exclude_none=True, by_alias=True)
