"""State that every replica of the shop's server reaches: one SQLite file on the machine (chapter 6).

    from lib import shared_state
    quotes = shared_state.SharedMap(path, "quotes")      # for shop_tools.create_server(quotes=...)
    answered = shared_state.SharedSet(path, "answered")  # for confirmations.OnceOnly(seen=...)

Each process that opens the same `path` sees the same entries. A map stores each value as a JSON text, never a pickle,
so a row that someone else wrote into the database can't run code when a replica reads it. By default a `SharedMap`
holds `shop_tools` quote records: `quote_to_json` turns the record's `Refund` into plain fields and its expiry, a
`time.monotonic()` deadline that means something only in the process that set it, into wall-clock seconds since the
epoch (`expires_at`), which every host reads the same way while their clocks are kept in sync; `quote_from_json`
turns a row back into a record whose deadline is on the reading process's own monotonic clock. Pass `encode` and
`decode` to store other values. Both classes have a `lock`, a reusable context manager that holds an exclusive file
lock on `path + ".lock"`, so a check-then-write by one replica can't interleave with another's; `shop_tools.create_server`
and `confirmations.OnceOnly` use a container's `lock` when it has one. `STORE_VARIABLE` names the environment
variable, `SHOP_STATE_STORE`, through which `lib.confirmations` gives a launched server the file's path.

A SQLite file stands in for the database a deployment would share; it serves processes on one machine only. The rows
are plain JSON and the expiry is absolute, so the same two tables can move into a shared database as they are.
"""
from __future__ import annotations

import fcntl
import json
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator, MutableMapping
from contextlib import contextmanager

STORE_VARIABLE = "SHOP_STATE_STORE"


def quote_to_json(quote: dict) -> str:
    """A `shop_tools` quote record as JSON: the refund as plain fields, the expiry as an absolute wall-clock time."""
    row = {key: value for key, value in quote.items() if key != "expires"}
    row["expires_at"] = time.time() + (quote["expires"] - time.monotonic())
    if quote["refund"] is not None:
        row["refund"] = quote["refund"].model_dump(mode="json")
    return json.dumps(row)


def quote_from_json(text: str) -> dict:
    """The record `quote_to_json` stored, with its `Refund` rebuilt and its expiry on this process's monotonic clock."""
    from lib.shop_tools import Refund
    row = json.loads(text)
    quote = {key: value for key, value in row.items() if key != "expires_at"}
    quote["expires"] = time.monotonic() + (row["expires_at"] - time.time())
    if row["refund"] is not None:
        quote["refund"] = Refund.model_validate(row["refund"])
    return quote


class FileLock:
    """An exclusive lock on a file, shared by every process and thread that uses the same path; reusable."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._held = threading.local()

    def __enter__(self) -> None:
        handle = open(self.path, "a")
        fcntl.flock(handle, fcntl.LOCK_EX)
        self._held.handle = handle

    def __exit__(self, *exc) -> None:
        handle = self._held.handle
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


class _Table:
    def __init__(self, path: str, table: str) -> None:
        self.path, self.table = path, table
        self.lock = FileLock(path + ".lock")
        with self._db() as db:
            db.execute(f"CREATE TABLE IF NOT EXISTS {table} (key TEXT PRIMARY KEY, value TEXT)")

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        """A connection that commits on success and is always closed."""
        connection = sqlite3.connect(self.path, timeout=10.0)
        try:
            with connection:
                yield connection
        finally:
            connection.close()


    def __contains__(self, key: object) -> bool:
        with self._db() as db:
            return db.execute(f"SELECT 1 FROM {self.table} WHERE key = ?", (key,)).fetchone() is not None

    def __len__(self) -> int:
        with self._db() as db:
            return db.execute(f"SELECT COUNT(*) FROM {self.table}").fetchone()[0]


class SharedMap(_Table, MutableMapping):
    """A string-keyed map in one table of a SQLite file, each value stored as the JSON text `encode` makes."""

    def __init__(self, path: str, table: str, *, encode: Callable[[object], str] = quote_to_json,
                 decode: Callable[[str], object] = quote_from_json) -> None:
        super().__init__(path, table)
        self.encode, self.decode = encode, decode

    def __getitem__(self, key: str):
        with self._db() as db:
            row = db.execute(f"SELECT value FROM {self.table} WHERE key = ?", (key,)).fetchone()
        if row is None:
            raise KeyError(key)
        return self.decode(row[0])

    def __setitem__(self, key: str, value) -> None:
        with self._db() as db:
            db.execute(f"INSERT OR REPLACE INTO {self.table} VALUES (?, ?)", (key, self.encode(value)))

    def __delitem__(self, key: str) -> None:
        with self._db() as db:
            if db.execute(f"DELETE FROM {self.table} WHERE key = ?", (key,)).rowcount == 0:
                raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        with self._db() as db:
            return iter([row[0] for row in db.execute(f"SELECT key FROM {self.table}")])


class SharedSet(_Table):
    """A set of strings in one table of a SQLite file: `in` and `add`, which is all `OnceOnly` needs."""

    def add(self, key: str) -> None:
        with self._db() as db:
            db.execute(f"INSERT OR IGNORE INTO {self.table} VALUES (?, NULL)", (key,))
