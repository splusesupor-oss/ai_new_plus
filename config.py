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
            support_contact=_clean(env.get("SUPPORT_CONTACT")),
            group_url=_clean(env.get("FOX_GROUP_URL")),
            channel_url=_clean(env.get("FOX_CHANNEL_URL")),
        )
