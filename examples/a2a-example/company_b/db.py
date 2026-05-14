from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sanction_entries (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          row TEXT NOT NULL UNIQUE
        )
        """
    )
    conn.commit()


def seed_if_empty(conn: sqlite3.Connection, rows: Iterable[str]) -> None:
    (count,) = conn.execute("SELECT COUNT(*) FROM sanction_entries").fetchone() or (0,)
    if count:
        return
    conn.executemany("INSERT OR IGNORE INTO sanction_entries(row) VALUES (?)", [(r,) for r in rows])
    conn.commit()


def fetch_sanction_list(db_path: Path) -> list[str]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        ensure_schema(conn)
        seed_if_empty(
            conn,
            [
                "Joe Quimby,S4928374,213 Church St",
                "C. Montgomery Burns,S9283746,1000 Mammon Lane",
                "Bob Johnson,C3456789,789 Pine Street",
            ],
        )
        cur = conn.execute("SELECT row FROM sanction_entries ORDER BY id ASC")
        return [r for (r,) in cur.fetchall()]
    finally:
        conn.close()

