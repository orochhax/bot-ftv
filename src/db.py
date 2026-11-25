from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

from src.models import Offer

TZ = ZoneInfo("America/Sao_Paulo")


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sent_offers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    store TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    price REAL NOT NULL,
                    old_price REAL,
                    discount_pct INTEGER NOT NULL,
                    affiliate_url TEXT NOT NULL,
                    sent_at TEXT NOT NULL,
                    UNIQUE(store, external_id)
                );

                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    fetched_count INTEGER NOT NULL,
                    approved_count INTEGER NOT NULL,
                    sent_count INTEGER NOT NULL,
                    error_count INTEGER NOT NULL,
                    error_summary TEXT
                );
                """
            )

    def can_send(self, offer: Offer, cooldown_days: int = 7, now: datetime | None = None) -> bool:
        now = now or datetime.now(TZ)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT price, sent_at FROM sent_offers WHERE store = ? AND external_id = ?",
                (offer.store, offer.external_id),
            ).fetchone()

        if row is None:
            return True

        last_sent = datetime.fromisoformat(row["sent_at"])
        if now - last_sent >= timedelta(days=cooldown_days):
            return True

        # Permite reenvio dentro do cooldown se cair >= 10% alem do ultimo preco enviado
        last_price = float(row["price"])
        return offer.price <= round(last_price * 0.90, 2)

    def record_sent(self, offer: Offer, now: datetime | None = None) -> None:
        now = now or datetime.now(TZ)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sent_offers (store, external_id, title, price, old_price, discount_pct, affiliate_url, sent_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(store, external_id) DO UPDATE SET
                    title = excluded.title,
                    price = excluded.price,
                    old_price = excluded.old_price,
                    discount_pct = excluded.discount_pct,
                    affiliate_url = excluded.affiliate_url,
                    sent_at = excluded.sent_at
                """,
                (
                    offer.store,
                    offer.external_id,
                    offer.title,
                    offer.price,
                    offer.old_price,
                    offer.discount_pct,
                    offer.url,
                    now.isoformat(),
                ),
            )

    def count_sent_today(self, now: datetime | None = None) -> int:
        now = now or datetime.now(TZ)
        day_prefix = now.strftime("%Y-%m-%d")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS total FROM sent_offers WHERE sent_at LIKE ?",
                (f"{day_prefix}%",),
            ).fetchone()
        return int(row["total"]) if row else 0

    def record_run(
        self,
        started_at: datetime,
        finished_at: datetime,
        fetched_count: int,
        approved_count: int,
        sent_count: int,
        error_count: int,
        error_summary: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (started_at, finished_at, fetched_count, approved_count, sent_count, error_count, error_summary)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    started_at.isoformat(),
                    finished_at.isoformat(),
                    fetched_count,
                    approved_count,
                    sent_count,
                    error_count,
                    error_summary[:1000],
                ),
            )
