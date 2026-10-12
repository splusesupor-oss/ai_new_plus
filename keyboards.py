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

from aiosplus.types import KeyboardButton, ReplyKeyboardMarkup

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
