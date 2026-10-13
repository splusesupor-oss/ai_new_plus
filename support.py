# -*- coding: utf-8 -*-
"""منطق بخش «ارتباط با پشتیبانی».

کاربر پیامش را می‌نویسد؛ ربات آن را همراه مشخصات کامل کاربر برای مدیر
می‌فرستد. مدیر روی همان پیام ریپلای می‌کند و ربات پاسخ را برای همان
کاربر می‌فرستد. ارتباط بین پیام مدیر و کاربر هم با شناسه پیام مدیر و
هم با کد پیگیری داخل متن (SUP-<id>) در دیتابیس نگهداری می‌شود تا پاسخ
حتی بعد از ری‌استارت ربات هم به کاربر درست برسد.
"""
from __future__ import annotations

import html
import re

from storage import UserRecord
from video_orders import user_display

# متنی که دقیقاً بعد از زدن «ارتباط با پشتیبانی» به کاربر نشان داده می‌شود
SUPPORT_PROMPT_TEXT = "پیام خودتون رو برای پشتیبانی بنویسید"

SUPPORT_SENT_TEXT = (
    "✅ پیام شما برای پشتیبانی ارسال شد.\n"
    "پاسخ پشتیبانی همین‌جا برایتان ارسال می‌شود."
)
SUPPORT_UNAVAILABLE_TEXT = (
    "پشتیبانی در حال حاضر در دسترس نیست. لطفاً بعداً دوباره تلاش کنید."
)
SUPPORT_SEND_FAILED_TEXT = (
    "ارسال پیام به پشتیبانی ناموفق بود. لطفاً دوباره تلاش کنید."
)
SUPPORT_REPLY_PREFIX = "💬 پاسخ پشتیبانی"

_REF_RE = re.compile(r"SUP-(\d+)")


def support_ref(ticket_id: int) -> str:
    return f"SUP-{ticket_id}"


def find_support_ref(text: str | None) -> int | None:
    """کد پیگیری را از متن پیام ریپلای‌شده پیدا می‌کند (مسیر پشتیبان)."""
    match = _REF_RE.search(text or "")
    return int(match.group(1)) if match else None


def support_admin_text(ticket_id: int, user: UserRecord | None, body: str) -> str:
    """پیام مدیر: مشخصات کامل کاربر + متن پیام او (HTML امن)."""
    username = (
        f"@{user.username.lstrip('@')}" if user and user.username else "بدون یوزرنیم"
    )
    name = (user.display_name or user.first_name) if user else None
    return (
        "<b>💬 پیام جدید پشتیبانی</b>\n"
        f"<b>کد پیگیری:</b> {support_ref(ticket_id)}\n"
        f"<b>نام کاربر:</b> {html.escape(name or '—')}\n"
        f"<b>یوزرنیم:</b> {html.escape(username)}\n"
        f"<b>کاربر:</b> {html.escape(user_display(user))}\n"
        f"<b>کد شش‌رقمی:</b> {html.escape(user.code if user else '—')}\n"
        f"<b>شناسه سروش‌پلاس:</b> {html.escape(user.user_key if user else '—')}\n"
        f"<b>شناسه چت:</b> {html.escape((user.chat_id if user else None) or '—')}\n"
        "\n"
        "<b>پیام کاربر:</b>\n"
        f"{html.escape(body or '—')}\n"
        "\n"
        "↩️ برای پاسخ به این کاربر، روی همین پیام <b>ریپلای</b> کنید و جواب را بفرستید."
    )


def support_admin_caption(ticket_id: int, user: UserRecord | None, body: str) -> str:
    """نسخه کپشن عکس برای پیام پشتیبانی تصویری (با سقف کپشن API)."""
    return support_admin_text(ticket_id, user, body)[:1000]
