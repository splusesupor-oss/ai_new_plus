# -*- coding: utf-8 -*-
"""منطق خالص مسیریابی پیام‌ها — بدون هیچ وابستگی به شبکه یا توکن.

این ماژول جدا نگه داشته شده تا رفتار همه دکمه‌ها و دستورها بدون
توکن واقعی و بدون ارسال پیام واقعی قابل آزمون باشد.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import texts


class _SettingsLike(Protocol):
    support_contact: str | None
    group_url: str | None
    channel_url: str | None


@dataclass(frozen=True)
class Reply:
    """پاسخی که ربات باید بدهد."""

    text: str
    show_main_keyboard: bool = True


def _normalize_command(text: str) -> str:
    """دستور را نرمال می‌کند: «/start@BotName» و «/start args» هم قبول است."""
    first = text.split(maxsplit=1)[0] if text else ""
    return first.split("@", 1)[0].lower()


def route_message(raw_text: str | None, settings: _SettingsLike) -> Reply:
    """متن ورودی کاربر را به پاسخ مناسب تبدیل می‌کند."""
    text = (raw_text or "").strip()

    # دستورهای نمایش منو
    if text == texts.MENU_TEXT_COMMAND or _normalize_command(text) in ("/start", "/menu"):
        return Reply(text=texts.WELCOME_TEXT, show_main_keyboard=True)

    # دکمه‌های منوی اصلی (مقایسه دقیق با همان عنوانی که روی دکمه است)
    # «ساخت ویدیو» و «سفارش‌های من» اینجا نیستند؛ در handlers با دیتابیس و
    # کیبورد شیشه‌ای پاسخ داده می‌شوند و قبل از این مسیر عمومی گرفته می‌شوند.
    if text == texts.BTN_CREATE_IMAGE:
        return Reply(text=texts.CREATE_IMAGE_SOON_TEXT)
    if text == texts.BTN_FREE_CREDIT:
        return Reply(text=texts.FREE_CREDIT_TEXT)
    if text == texts.BTN_SAMPLES:
        return Reply(text=texts.SAMPLES_TEXT)
    if text == texts.BTN_SUPPORT:
        return Reply(text=texts.support_text(settings.support_contact))
    if text == texts.BTN_GROUP:
        return Reply(text=texts.group_text(settings.group_url))
    if text == texts.BTN_CHANNEL:
        return Reply(text=texts.channel_text(settings.channel_url))

    # هر پیام ناشناخته یا بدون متن (عکس، استیکر و…)
    return Reply(text=texts.UNKNOWN_TEXT, show_main_keyboard=True)
