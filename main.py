# -*- coding: utf-8 -*-
"""نقطه ورود ربات هوش مصنوعی روباه — ربات رسمی سروش‌پلاس (Bot API + توکن).

اجرا در Termux:
    bash run.sh
یا:
    python main.py

توکن فقط از متغیر محیطی BOT_TOKEN در فایل .env خوانده می‌شود و
هرگز در لاگ چاپ نمی‌شود. در این مرحله فقط منوی اصلی فعال است.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_env_file() -> None:
    """فایل .env کنار پروژه را می‌خواند (با fallback داخلی اگر dotenv نصب نباشد)."""
    env_path = BASE_DIR / ".env"
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path)
        return
    except ImportError:
        pass
    # Fallback ساده تا ربات بدون python-dotenv هم در Termux اجرا شود.
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


async def _run() -> int:
    from aiosplus import Bot
    from aiosplus.exceptions import NetworkError, SoroushUnauthorized
    from aiosplus.types import BotCommand

    from config import Settings
    from handlers import build_dispatcher

    try:
        settings = Settings.from_environ()
    except Exception as exc:  # ConfigError با پیام فارسی آماده نمایش است
        print(f"❌ {exc}", file=sys.stderr)
        return 2

    bot = Bot(token=settings.bot_token)
    dp = build_dispatcher(settings)

    # بررسی توکن و اتصال قبل از شروع دریافت پیام‌ها
    logging.info("در حال اتصال به سروش‌پلاس و بررسی توکن ربات...")
    try:
        me = await bot.get_me()
        username = f" (@{me.username})" if me.username else ""
        logging.info("ربات با موفقیت متصل شد: %s%s", me.first_name, username)
    except SoroushUnauthorized:
        logging.error(
            "توکن ربات نامعتبر است. توکن را از BotFather سروش‌پلاس دوباره "
            "دریافت کنید و فقط در فایل .env (متغیر BOT_TOKEN) قرار دهید."
        )
        await bot.close_session()
        return 2
    except NetworkError:
        logging.warning(
            "در بررسی اولیه اتصال به سروش‌پلاس خطای شبکه رخ داد؛ "
            "دریافت پیام‌ها ادامه پیدا می‌کند و اتصال به‌صورت خودکار دوباره تلاش می‌شود."
        )
    except Exception:  # خطای پیش‌بینی‌نشده API نباید توکن را لو بدهد
        logging.exception("خطای پیش‌بینی‌نشده هنگام بررسی اولیه ربات")
        await bot.close_session()
        return 1

    # منوی دستورات رسمی ربات (/start و /menu) — خطا در آن نباید ربات را متوقف کند
    try:
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="شروع و نمایش منوی اصلی"),
                BotCommand(command="menu", description="نمایش منوی اصلی"),
            ]
        )
    except Exception:
        logging.warning("ثبت منوی دستورات انجام نشد؛ ربات بدون آن ادامه می‌دهد.", exc_info=True)

    logging.info("🦊 ربات روباه در حال اجراست... برای توقف Ctrl+C را بزنید.")
    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logging.info("ربات با درخواست کاربر متوقف شد.")
    finally:
        await bot.close_session()
    return 0


def main() -> int:
    _load_env_file()
    _setup_logging()
    try:
        return asyncio.run(_run())
    except KeyboardInterrupt:
        print("\nربات متوقف شد.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
