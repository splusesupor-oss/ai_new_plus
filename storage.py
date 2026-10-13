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
                """
            )

    # ---------- کاربران و شناسه شش‌رقمی ----------
    def get_or_create_user(
        self, user_key: str, chat_id: str | None = None, first_name: str | None = None
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
                if chat_id and (row["chat_id"] != str(chat_id) or row["first_name"] != first_name):
                    conn.execute(
                        "UPDATE users SET chat_id=?, first_name=? WHERE user_key=?",
                        (str(chat_id), first_name, user_key),
                    )
                    row = conn.execute(
                        "SELECT * FROM users WHERE user_key=?", (user_key,)
                    ).fetchone()
                return self._to_user(row)
            for _ in range(100):
                code = str(self._rand.randint(CODE_MIN, CODE_MAX))
                try:
                    conn.execute(
                        "INSERT INTO users(user_key, code, chat_id, first_name, created_at)"
                        " VALUES(?,?,?,?,?)",
                        (user_key, code, str(chat_id) if chat_id else None, first_name, _now()),
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
        return UserRecord(
            user_key=row["user_key"],
            code=row["code"],
            chat_id=row["chat_id"],
            first_name=row["first_name"],
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

    @staticmethod
    def _to_order(row: sqlite3.Row) -> Order:
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
