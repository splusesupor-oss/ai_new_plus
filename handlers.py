# -*- coding: utf-8 -*-
"""هندلرهای ربات رسمی سروش‌پلاس (کتابخانه aiosplus روی Bot API رسمی).

ترتیب ثبت هندلرها مهم است: کتابخانه اولین هندلر منطبق را اجرا می‌کند،
پس دستورها و دکمه‌ها قبل از هندلر پیش‌فرض (fallback) ثبت می‌شوند.
در این مرحله هیچ سرویس هوش مصنوعی، پرداخت یا اعتباری متصل نیست.
"""
from __future__ import annotations

import logging

from aiosplus import Dispatcher
from aiosplus.filters import Command, Text
from aiosplus.types import Message

import texts
from bot_logic import route_message
from config import Settings
from keyboards import build_main_keyboard

logger = logging.getLogger(__name__)


async def _answer(message: Message, settings: Settings) -> None:
    """پاسخ یک پیام را بر اساس منطق خالص bot_logic ارسال می‌کند."""
    reply = route_message(message.text, settings)
    await message.answer(
        reply.text,
        reply_markup=build_main_keyboard() if reply.show_main_keyboard else None,
    )


def build_dispatcher(settings: Settings) -> Dispatcher:
    """Dispatcher را می‌سازد و همه هندلرهای این مرحله را ثبت می‌کند."""
    dp = Dispatcher()

    @dp.message(Command("start"))
    async def cmd_start(message: Message) -> None:
        await _answer(message, settings)

    @dp.message(Command("menu"))
    async def cmd_menu(message: Message) -> None:
        await _answer(message, settings)

    @dp.message(Text(text=texts.MENU_TEXT_COMMAND))
    async def cmd_menu_fa(message: Message) -> None:
        await _answer(message, settings)

    @dp.message(
        Text(
            text=[
                texts.BTN_CREATE_IMAGE,
                texts.BTN_CREATE_VIDEO,
                texts.BTN_MY_ORDERS,
                texts.BTN_FREE_CREDIT,
                texts.BTN_SAMPLES,
                texts.BTN_SUPPORT,
                texts.BTN_GROUP,
                texts.BTN_CHANNEL,
            ]
        )
    )
    async def on_main_menu_button(message: Message) -> None:
        await _answer(message, settings)

    @dp.message()
    async def fallback(message: Message) -> None:
        logger.info("پیام ناشناخته دریافت شد (chat_id=%s)", message.chat.id)
        await _answer(message, settings)

    return dp
