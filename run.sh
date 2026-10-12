#!/usr/bin/env bash
# اجرای ساده ربات روباه در Termux اندروید:  bash run.sh
set -e
cd "$(dirname "$0")"

if ! command -v python >/dev/null 2>&1 && ! command -v python3 >/dev/null 2>&1; then
  echo "❌ پایتون پیدا نشد. در Termux اجرا کنید:  pkg install python"
  exit 1
fi
PY="$(command -v python || command -v python3)"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "⚠️ فایل .env ساخته شد. توکن ربات را داخل آن قرار دهید:"
  echo "   nano .env"
  echo "سپس دوباره اجرا کنید:  bash run.sh"
  exit 1
fi

if ! "$PY" -c "import aiosplus, dotenv" >/dev/null 2>&1; then
  echo "📦 در حال نصب وابستگی‌ها..."
  "$PY" -m pip install -r requirements.txt
fi

# پوشه داده‌ها ساخته می‌شود و با اجرای مجدد حذف نمی‌شود
mkdir -p data logs
exec "$PY" main.py
