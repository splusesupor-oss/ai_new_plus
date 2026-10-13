# -*- coding: utf-8 -*-
"""ذخیره‌سازی محلی ربات با SQLite (کتابخانه استاندارد پایتون).

داده‌ها در فایل data/bot.db نگهداری می‌شوند تا با ری‌استارت ربات
از بین نروند. این فایل در .gitignore است و روی گیت‌هاب نمی‌رود.

نکته مهم: «شناسه شش‌رقمی کاربر» فقط یک کد داخلی برای شناسایی کاربر
است و هرگز به‌جای شناسه چت سروش‌پلاس (chat_id) استفاده نمی‌شود؛
هر دو جداگانه ذخیره می‌شوند.
"""
from __future__ import annotations

import secrets
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

CODE_MIN = 100000
CODE_MAX = 999999

DAILY_FREE_CREDIT = 50
IMAGE_ORDER_COST = 10


def tehran_today():
    """تاریخ امروز به وقت تهران (ریست اعتبار ساعت ۰۰:۰۰ تهران)."""
    from datetime import datetime, timedelta, timezone

    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Tehran")).date().isoformat()
    except Exception:  # در نبود tzdata، تهران ثابت UTC+3:30 است
        tz = timezone(timedelta(hours=3, minutes=30))
        return datetime.now(tz).date().isoformat()

STATUS_DRAFT = "draft"
STATUS_AWAITING_RECEIPT = "awaiting_receipt"
STATUS_PENDING_REVIEW = "pending_review"
STATUS_PAYMENT_APPROVED = "payment_approved"
STATUS_PROCESSING = "processing"
STATUS_COMPLETED = "completed"
STATUS_REJECTED = "rejected"

ORDER_STATUSES = {
    STATUS_AWAITING_RECEIPT,
    STATUS_PENDING_REVIEW,
    STATUS_PAYMENT_APPROVED,
    STATUS_PROCESSING,
    STATUS_COMPLETED,
    STATUS_REJECTED,
}

# وضعیت‌هایی که یعنی «یک سفارش ناتمام»؛ برای هر کاربر حداکثر یکی از این‌ها
ACTIVE_STATUSES = (STATUS_DRAFT, STATUS_AWAITING_RECEIPT)


def default_db_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "bot.db"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@dataclass(frozen=True)
class UserRecord:
    user_key: str  # شناسه عددی حساب سروش‌پلاس کاربر (از API)، به‌صورت رشته
    code: str  # شناسه شش‌رقمی داخلی کاربر
    chat_id: str | None
    first_name: str | None
    created_at: str
    username: str | None = None  # یوزرنیم سروش‌پلاس، اگر داشته باشد
    display_name: str | None = None  # نام نمایشی (جایگزین یوزرنیم)
    is_blocked: bool = False
    credit_balance: int = DAILY_FREE_CREDIT
    credit_date: str | None = None


@dataclass(frozen=True)
class SupportMessage:
    """یک پیام پشتیبانی کاربر و پیام متناظر آن نزد مدیر."""

    id: int
    user_key: str
    user_chat_id: str | None
    admin_chat_id: str | None
    admin_message_id: str | None  # شناسه پیام ربات در چت مدیر (برای ریپلای)
    user_message_id: str | None
    created_at: str


@dataclass(frozen=True)
class Order:
    id: int
    user_key: str
    model: str | None
    duration_seconds: int | None
    amount_toman: int | None
    status: str
    receipt_file_id: str | None
    receipt_requested: bool
    created_at: str
    updated_at: str
    order_type: str | None = None  # text | photo
    request_text: str | None = None  # متن درخواست کاربر یا توضیح عکس
    request_photo_file_id: str | None = None
    delivered_video_file_id: str | None = None
    service: str = "video"  # video | image
    image_mode: str | None = None  # gen | edit | face
    credit_cost: int = 0
    delivered_file_id: str | None = None


class Storage:
    """دسترسی امن و هم‌زمان‌روا به دیتابیس محلی سفارش‌ها و کاربران."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._rand = secrets.SystemRandom()
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_key TEXT PRIMARY KEY,
                    code TEXT NOT NULL UNIQUE,
                    chat_id TEXT,
                    first_name TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_key TEXT NOT NULL REFERENCES users(user_key),
                    model TEXT,
                    duration_seconds INTEGER,
                    amount_toman INTEGER,
                    status TEXT NOT NULL DEFAULT 'draft',
                    receipt_file_id TEXT,
                    receipt_requested INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_order
                    ON orders(user_key) WHERE status IN ('draft', 'awaiting_receipt');
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
                CREATE TABLE IF NOT EXISTS flow_states (
                    user_key TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    payload TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS support_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_key TEXT NOT NULL REFERENCES users(user_key),
                    user_chat_id TEXT,
                    admin_chat_id TEXT,
                    admin_message_id TEXT,
                    user_message_id TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_support_admin_message
                    ON support_messages(admin_chat_id, admin_message_id);
                """
            )
            # مهاجرت دیتابیس‌های قبلی: ستون‌های جدید بدون حذف داده‌های فعلی
            for table, columns in {
                "users": {
                    "username": "TEXT",
                    "display_name": "TEXT",
                    "is_blocked": "INTEGER NOT NULL DEFAULT 0",
                    "credit_balance": "INTEGER NOT NULL DEFAULT 50",
                    "credit_date": "TEXT",
                },
                "orders": {
                    "order_type": "TEXT",
                    "request_text": "TEXT",
                    "request_photo_file_id": "TEXT",
                    "delivered_video_file_id": "TEXT",
                    "service": "TEXT NOT NULL DEFAULT 'video'",
                    "image_mode": "TEXT",
                    "credit_cost": "INTEGER NOT NULL DEFAULT 0",
                    "delivered_file_id": "TEXT",
                },
            }.items():
                existing = {
                    row["name"]
                    for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
                }
                for col, col_type in columns.items():
                    if col not in existing:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")

    # ---------- کاربران و شناسه شش‌رقمی ----------
    def get_or_create_user(
        self,
        user_key: str,
        chat_id: str | None = None,
        first_name: str | None = None,
        username: str | None = None,
        display_name: str | None = None,
    ) -> UserRecord:
        """کاربر را برمی‌گرداند و اگر اولین بار است، کد شش‌رقمی یکتا می‌سازد.

        کد ساخته‌شده پایدار است و با اجرای مجدد /start هرگز تغییر نمی‌کند.
        """
        user_key = str(user_key)
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE user_key=?", (user_key,)
            ).fetchone()
            if row is not None:
                # مقدار خالی جدید، اطلاعات قبلی کاربر (مثل یوزرنیم) را پاک نمی‌کند
                first_name = first_name if first_name is not None else row["first_name"]
                username = username if username is not None else row["username"]
                display_name = display_name if display_name is not None else row["display_name"]
                if chat_id and (
                    row["chat_id"] != str(chat_id)
                    or row["first_name"] != first_name
                    or row["username"] != username
                    or row["display_name"] != display_name
                ):
                    conn.execute(
                        "UPDATE users SET chat_id=?, first_name=?, username=?, display_name=?"
                        " WHERE user_key=?",
                        (str(chat_id), first_name, username, display_name, user_key),
                    )
                    row = conn.execute(
                        "SELECT * FROM users WHERE user_key=?", (user_key,)
                    ).fetchone()
                return self._to_user(row)
            for _ in range(100):
                code = str(self._rand.randint(CODE_MIN, CODE_MAX))
                try:
                    conn.execute(
                        "INSERT INTO users(user_key, code, chat_id, first_name, username,"
                        " display_name, created_at) VALUES(?,?,?,?,?,?,?)",
                        (
                            user_key,
                            code,
                            str(chat_id) if chat_id else None,
                            first_name,
                            username,
                            display_name,
                            _now(),
                        ),
                    )
                    break
                except sqlite3.IntegrityError:
                    existing = conn.execute(
                        "SELECT * FROM users WHERE user_key=?", (user_key,)
                    ).fetchone()
                    if existing is not None:  # ساخت هم‌زمان توسط درخواست دیگر
                        return self._to_user(existing)
                    continue  # کد تکراری بود؛ کد دیگری امتحان کن
            else:
                raise RuntimeError("ساخت شناسه شش‌رقمی یکتا ممکن نشد")
            row = conn.execute(
                "SELECT * FROM users WHERE user_key=?", (user_key,)
            ).fetchone()
            return self._to_user(row)

    def get_user(self, user_key: str) -> UserRecord | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE user_key=?", (str(user_key),)
            ).fetchone()
            return self._to_user(row) if row else None

    @staticmethod
    def _to_user(row: sqlite3.Row) -> UserRecord:
        keys = row.keys()
        return UserRecord(
            user_key=row["user_key"],
            code=row["code"],
            chat_id=row["chat_id"],
            first_name=row["first_name"],
            created_at=row["created_at"],
            username=row["username"] if "username" in keys else None,
            display_name=row["display_name"] if "display_name" in keys else None,
            is_blocked=bool(row["is_blocked"]) if "is_blocked" in keys else False,
            credit_balance=(
                int(row["credit_balance"]) if "credit_balance" in keys and row["credit_balance"] is not None else DAILY_FREE_CREDIT
            ),
            credit_date=row["credit_date"] if "credit_date" in keys else None,
        )

    # ---------- اعتبار رایگان روزانه ----------
    def ensure_daily_credit(self, user_key: str) -> int:
        """موجودی امروز کاربر؛ با شروع روز تازه تهران، خودکار ۵۰ می‌شود."""
        today = tehran_today()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT credit_balance, credit_date FROM users WHERE user_key=?",
                (str(user_key),),
            ).fetchone()
            if row is None:
                return 0
            if row["credit_date"] != today:
                conn.execute(
                    "UPDATE users SET credit_balance=?, credit_date=? WHERE user_key=?",
                    (DAILY_FREE_CREDIT, today, str(user_key)),
                )
                return DAILY_FREE_CREDIT
            return int(row["credit_balance"])

    def add_credit(self, user_key: str, amount: int) -> int:
        """برگرداندن اعتبار (مثلاً رد شدن سفارش تصویر توسط مدیر)."""
        self.ensure_daily_credit(user_key)
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE users SET credit_balance=credit_balance+? WHERE user_key=?",
                (amount, str(user_key)),
            )
            row = conn.execute(
                "SELECT credit_balance FROM users WHERE user_key=?", (str(user_key),)
            ).fetchone()
            return int(row["credit_balance"]) if row else 0


    def list_users(self, limit: int = 100000) -> list[UserRecord]:
        """همه اعضای ثبت‌شده ربات (برای دستور اعضا و اطلاع‌رسانی همگانی)."""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM users ORDER BY created_at, user_key LIMIT ?", (limit,)
            ).fetchall()
            return [self._to_user(r) for r in rows]

    def count_users(self) -> int:
        with self._lock, self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"])

    def get_user_by_code(self, code: str) -> UserRecord | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE code=?", (str(code),)
            ).fetchone()
            return self._to_user(row) if row else None

    def set_blocked_by_code(self, code: str, blocked: bool) -> UserRecord | None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE users SET is_blocked=? WHERE code=?",
                (1 if blocked else 0, str(code)),
            )
        return self.get_user_by_code(code)

    # ---------- پشتیبانی (پیام کاربر ← مدیر، پاسخ با ریپلای) ----------
    def create_support_message(
        self,
        user_key: str,
        user_chat_id: str | None,
        admin_chat_id: str | None,
        user_message_id: str | None = None,
    ) -> SupportMessage:
        """تیکت پشتیبانی می‌سازد تا پاسخ مدیر دقیقاً به همین کاربر برسد."""
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO support_messages(user_key, user_chat_id, admin_chat_id,"
                " user_message_id, created_at) VALUES(?,?,?,?,?)",
                (
                    str(user_key),
                    str(user_chat_id) if user_chat_id else None,
                    str(admin_chat_id) if admin_chat_id else None,
                    str(user_message_id) if user_message_id else None,
                    _now(),
                ),
            )
            ticket_id = int(cur.lastrowid)
        return self.get_support_message(ticket_id)  # type: ignore[return-value]

    def set_support_admin_message(self, ticket_id: int, admin_message_id: str) -> None:
        """شناسه پیامی که ربات در چت مدیر فرستاد؛ کلید اتصال ریپلای مدیر است."""
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE support_messages SET admin_message_id=? WHERE id=?",
                (str(admin_message_id), ticket_id),
            )

    def get_support_message(self, ticket_id: int) -> SupportMessage | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM support_messages WHERE id=?", (ticket_id,)
            ).fetchone()
            return self._to_support(row) if row else None

    def get_support_by_admin_message(
        self, admin_chat_id: str, admin_message_id: str
    ) -> SupportMessage | None:
        """تیکت متناظر با پیامی که مدیر رویش ریپلای کرده است."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM support_messages WHERE admin_chat_id=?"
                " AND admin_message_id=? ORDER BY id DESC LIMIT 1",
                (str(admin_chat_id), str(admin_message_id)),
            ).fetchone()
            return self._to_support(row) if row else None

    @staticmethod
    def _to_support(row: sqlite3.Row) -> SupportMessage:
        return SupportMessage(
            id=int(row["id"]),
            user_key=row["user_key"],
            user_chat_id=row["user_chat_id"],
            admin_chat_id=row["admin_chat_id"],
            admin_message_id=row["admin_message_id"],
            user_message_id=row["user_message_id"],
            created_at=row["created_at"],
        )

    # ---------- سفارش‌ها ----------
    def get_active_order(self, user_key: str) -> Order | None:
        """سفارش ناتمام (پیش‌نویس/در انتظار رسید) کاربر، اگر وجود داشته باشد."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM orders WHERE user_key=? AND status IN ('draft','awaiting_receipt')"
                " ORDER BY id DESC LIMIT 1",
                (str(user_key),),
            ).fetchone()
            return self._to_order(row) if row else None

    def create_or_get_draft(self, user_key: str) -> Order:
        """پیش‌نویس فعال کاربر را برمی‌گرداند یا یکی می‌سازد (ضد سفارش تکراری)."""
        active = self.get_active_order(user_key)
        if active is not None:
            return active
        with self._lock, self._connect() as conn:
            try:
                cur = conn.execute(
                    "INSERT INTO orders(user_key, status, created_at, updated_at)"
                    " VALUES(?, 'draft', ?, ?)",
                    (str(user_key), _now(), _now()),
                )
                order_id = int(cur.lastrowid)
            except sqlite3.IntegrityError:  # هم‌زمان ساخته شده است
                return self.get_active_order(user_key)  # type: ignore[return-value]
            row = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            return self._to_order(row)

    def set_order_model(self, order_id: int, user_key: str, model: str) -> Order | None:
        """مدل را روی همان سفارش کاربر ثبت می‌کند؛ بعد از ثبت رسید قابل تغییر نیست."""
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE orders SET model=?, updated_at=? WHERE id=? AND user_key=?"
                " AND status IN ('draft','awaiting_receipt') AND receipt_file_id IS NULL",
                (model, _now(), order_id, str(user_key)),
            )
        return self.get_order(order_id)

    def set_order_duration(
        self, order_id: int, user_key: str, seconds: int, amount_toman: int
    ) -> Order | None:
        """مدت و مبلغ دقیق را ثبت و سفارش را «در انتظار رسید» می‌کند (همان سفارش)."""
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE orders SET duration_seconds=?, amount_toman=?,"
                " status='awaiting_receipt', updated_at=? WHERE id=? AND user_key=?"
                " AND status IN ('draft','awaiting_receipt') AND receipt_file_id IS NULL",
                (seconds, amount_toman, _now(), order_id, str(user_key)),
            )
        return self.get_order(order_id)

    def request_receipt(self, order_id: int, user_key: str) -> Order | None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE orders SET receipt_requested=1, updated_at=?"
                " WHERE id=? AND user_key=? AND status='awaiting_receipt'",
                (_now(), order_id, str(user_key)),
            )
        return self.get_order(order_id)

    def find_receipt_candidate(self, user_key: str) -> Order | None:
        """سفارشی که کاربر برایش روی «ارسال رسید» زده و منتظر تصویر رسید است."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM orders WHERE user_key=? AND status='awaiting_receipt'"
                " AND receipt_requested=1 AND receipt_file_id IS NULL"
                " ORDER BY id DESC LIMIT 1",
                (str(user_key),),
            ).fetchone()
            return self._to_order(row) if row else None

    def attach_receipt(self, order_id: int, user_key: str, file_id: str) -> bool:
        """رسید را فقط یک بار ثبت می‌کند و وضعیت را pending_review می‌کند.

        True یعنی همین حالا ثبت شد؛ False یعنی قبلاً ثبت شده یا وضعیت نامعتبر است.
        تا تأیید مدیر، وضعیت هرگز payment_approved نمی‌شود.
        """
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE orders SET receipt_file_id=?, status='pending_review', updated_at=?"
                " WHERE id=? AND user_key=? AND status='awaiting_receipt'"
                " AND receipt_file_id IS NULL",
                (file_id, _now(), order_id, str(user_key)),
            )
            return cur.rowcount == 1

    def get_order(self, order_id: int) -> Order | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            return self._to_order(row) if row else None

    def list_user_orders(self, user_key: str, limit: int = 10) -> list[Order]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM orders WHERE user_key=? ORDER BY id DESC LIMIT ?",
                (str(user_key), limit),
            ).fetchall()
            return [self._to_order(r) for r in rows]

    def list_orders(self, status: str | None = None, limit: int = 20) -> list[Order]:
        with self._lock, self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM orders WHERE status=? ORDER BY id DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            return [self._to_order(r) for r in rows]

    def update_status(self, order_id: int, new_status: str) -> Order | None:
        if new_status not in ORDER_STATUSES and new_status != STATUS_DRAFT:
            raise ValueError(f"وضعیت نامعتبر سفارش: {new_status}")
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE orders SET status=?, updated_at=? WHERE id=?",
                (new_status, _now(), order_id),
            )
        return self.get_order(order_id)

    def set_order_content(
        self,
        order_id: int,
        user_key: str,
        order_type: str,
        request_text: str | None,
        request_photo_file_id: str | None = None,
    ) -> Order | None:
        """نوع سفارش و متن/عکس درخواستی را روی پیش‌نویس همان کاربر ثبت می‌کند."""
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE orders SET order_type=?, request_text=?, request_photo_file_id=?,"
                " updated_at=? WHERE id=? AND user_key=? AND status='draft'"
                " AND receipt_file_id IS NULL",
                (order_type, request_text, request_photo_file_id, _now(), order_id, str(user_key)),
            )
        return self.get_order(order_id)

    def complete_delivery(self, order_id: int, video_file_id: str) -> Order | None:
        """تحویل نهایی: ویدیو برای کاربر رفت و سفارش completed می‌شود."""
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE orders SET delivered_video_file_id=?, status='completed',"
                " updated_at=? WHERE id=?",
                (video_file_id, _now(), order_id),
            )
        return self.get_order(order_id)

    def create_image_order(
        self,
        user_key: str,
        image_mode: str,
        model: str,
        request_text: str,
        request_photo_file_id: str | None = None,
    ) -> Order | None:
        """سفارش تصویر را فقط اگر اعتبار کافی باشد ثبت و ۱۰ اعتبار کم می‌کند.

        کسر اعتبار و ثبت سفارش اتمیک است؛ موجودی هرگز منفی نمی‌شود و
        سفارش بدون اعتبار ساخته نمی‌شود. None یعنی اعتبار کافی نیست.
        """
        self.ensure_daily_credit(user_key)
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE users SET credit_balance=credit_balance-? WHERE user_key=?"
                " AND credit_balance>=?",
                (IMAGE_ORDER_COST, str(user_key), IMAGE_ORDER_COST),
            )
            if cur.rowcount != 1:
                return None
            cur = conn.execute(
                "INSERT INTO orders(user_key, model, status, service, image_mode,"
                " request_text, request_photo_file_id, credit_cost, created_at, updated_at)"
                " VALUES(?,?, 'pending_review', 'image', ?, ?, ?, ?, ?, ?)",
                (
                    str(user_key),
                    model,
                    image_mode,
                    request_text,
                    request_photo_file_id,
                    IMAGE_ORDER_COST,
                    _now(),
                    _now(),
                ),
            )
            order_id = int(cur.lastrowid)
        return self.get_order(order_id)

    def complete_image_delivery(self, order_id: int, file_id: str) -> Order | None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE orders SET delivered_file_id=?, status='completed', updated_at=?"
                " WHERE id=? AND service='image'",
                (file_id, _now(), order_id),
            )
        return self.get_order(order_id)

    @staticmethod
    def _to_order(row: sqlite3.Row) -> Order:
        keys = row.keys()
        return Order(
            id=int(row["id"]),
            user_key=row["user_key"],
            model=row["model"],
            duration_seconds=row["duration_seconds"],
            amount_toman=row["amount_toman"],
            status=row["status"],
            receipt_file_id=row["receipt_file_id"],
            receipt_requested=bool(row["receipt_requested"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            order_type=row["order_type"] if "order_type" in keys else None,
            request_text=row["request_text"] if "request_text" in keys else None,
            request_photo_file_id=(
                row["request_photo_file_id"] if "request_photo_file_id" in keys else None
            ),
            delivered_video_file_id=(
                row["delivered_video_file_id"] if "delivered_video_file_id" in keys else None
            ),
            service=row["service"] if "service" in keys and row["service"] else "video",
            image_mode=row["image_mode"] if "image_mode" in keys else None,
            credit_cost=int(row["credit_cost"]) if "credit_cost" in keys and row["credit_cost"] is not None else 0,
            delivered_file_id=row["delivered_file_id"] if "delivered_file_id" in keys else None,
        )

    # ---------- تنظیمات دائمی (مثل ویدیوی پیش‌فرض) -------
    def get_setting(self, key: str) -> str | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key=?", (key,)
            ).fetchone()
            return row["value"] if row else None

    def set_setting(self, key: str, value: str | None) -> None:
        with self._lock, self._connect() as conn:
            if value is None:
                conn.execute("DELETE FROM app_settings WHERE key=?", (key,))
            else:
                conn.execute(
                    "INSERT INTO app_settings(key, value) VALUES(?,?)"
                    " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, value),
                )

    # ---------- وضعیت موقت گفتگو (مثلاً «مدیر در حال تنظیم ویدیو است») ----
    def set_flow_state(self, user_key: str, state: str, payload: str | None = None) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO flow_states(user_key, state, payload, updated_at) VALUES(?,?,?,?)"
                " ON CONFLICT(user_key) DO UPDATE SET state=excluded.state,"
                " payload=excluded.payload, updated_at=excluded.updated_at",
                (str(user_key), state, payload, _now()),
            )

    def get_flow_state(self, user_key: str) -> tuple[str, str | None] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT state, payload FROM flow_states WHERE user_key=?", (str(user_key),)
            ).fetchone()
            return (row["state"], row["payload"]) if row else None

    def clear_flow_state(self, user_key: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM flow_states WHERE user_key=?", (str(user_key),))
