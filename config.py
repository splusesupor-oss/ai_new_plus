# -*- coding: utf-8 -*-
"""تنظیمات ربات — فقط از متغیرهای محیطی (فایل .env) خوانده می‌شود.

قانون امنیتی پروژه: توکن هرگز داخل کد، لاگ یا گیت قرار نمی‌گیرد.
تنها منبع توکن، متغیر محیطی BOT_TOKEN است.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


class ConfigError(RuntimeError):
    """خطای تنظیمات که باید با پیام فارسی و قابل‌فهم به کاربر/اپراتور نشان داده شود."""


# مقادیر پیش‌فرض مدیر و پرداخت؛ با متغیرهای محیطی (.env) قابل تغییرند.
# مدیر اصلی ربات:
DEFAULT_ADMIN_CHAT_ID = "37858988"
DEFAULT_ADMIN_USERNAME = "osine2"
DEFAULT_SUPPORT_CONTACT = "@osine2"
# اطلاعات پرداخت پیش‌فرض (همان کارت داخل تصویر assets/payment_card.jpg):
DEFAULT_PAYMENT_CARD_NUMBER = "6277601447969161"
DEFAULT_PAYMENT_CARD_HOLDER = "بشار"


def _clean(value: str | None) -> str | None:
    """فاصله‌های اطراف را حذف می‌کند؛ مقدار خالی یعنی «تنظیم نشده»."""
    if value is None:
        return None
    value = value.strip()
    return value or None


@dataclass(frozen=True)
class Settings:
    """تنظیمات زمان اجرا. فیلدهای اختیاری اگر تنظیم نشوند None هستند."""

    bot_token: str
    support_contact: str | None = None
    group_url: str | None = None
    channel_url: str | None = None
    # مدیر ربات: شناسه عددی چت/حساب مدیر در سروش‌پلاس (نه شناسه شش‌رقمی داخلی)
    admin_chat_id: str | None = None
    admin_username: str | None = None
    # اطلاعات پرداخت: فقط از .env خوانده می‌شود و در کد/GitHub قرار نمی‌گیرد
    payment_card_number: str | None = None
    payment_card_holder: str | None = None
    # مسیر فایل محلی تصویر راهنمای پرداخت (اختیاری)
    payment_guide_image: str | None = None

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if environ is None else environ
        token = _clean(env.get("BOT_TOKEN"))
        if not token:
            raise ConfigError(
                "توکن ربات پیدا نشد.\n"
                "فایل .env را از روی .env.example بسازید و توکن ربات رسمی "
                "سروش‌پلاس را فقط در متغیر BOT_TOKEN قرار دهید.\n"
                "مثال اجرا در Termux:\n"
                "  cp .env.example .env\n"
                "  nano .env"
            )
        return cls(
            bot_token=token,
            support_contact=_clean(env.get("SUPPORT_CONTACT")) or DEFAULT_SUPPORT_CONTACT,
            group_url=_clean(env.get("FOX_GROUP_URL")),
            channel_url=_clean(env.get("FOX_CHANNEL_URL")),
            admin_chat_id=_clean(env.get("ADMIN_CHAT_ID")) or DEFAULT_ADMIN_CHAT_ID,
            admin_username=_clean(env.get("ADMIN_USERNAME")) or DEFAULT_ADMIN_USERNAME,
            payment_card_number=_clean(env.get("PAYMENT_CARD_NUMBER"))
            or DEFAULT_PAYMENT_CARD_NUMBER,
            payment_card_holder=_clean(env.get("PAYMENT_CARD_HOLDER"))
            or DEFAULT_PAYMENT_CARD_HOLDER,
            payment_guide_image=_clean(env.get("PAYMENT_GUIDE_IMAGE")),
        )
