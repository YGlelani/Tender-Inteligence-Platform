"""A small async pool/connection wrapper around sqlite3."""
import asyncio
import sqlite3


class SQLiteConnection:
    def __init__(self, connection):
        self.connection = connection

    def _fetch(self, query, params):
        return [dict(row) for row in self.connection.execute(query, params).fetchall()]

    def _fetchrow(self, query, params):
        row = self.connection.execute(query, params).fetchone()
        return dict(row) if row is not None else None

    def _fetchval(self, query, params):
        row = self.connection.execute(query, params).fetchone()
        return row[0] if row else None

    def _execute(self, query, params):
        if params:
            self.connection.execute(query, params)
        else:
            self.connection.executescript(query)
        self.connection.commit()

    # Run blocking sqlite3 calls in a worker thread so they don't block the event loop.
    async def fetch(self, query, *params):
        return await asyncio.to_thread(self._fetch, query, params)

    async def fetchrow(self, query, *params):
        return await asyncio.to_thread(self._fetchrow, query, params)

    async def fetchval(self, query, *params):
        return await asyncio.to_thread(self._fetchval, query, params)

    async def execute(self, query, *params):
        await asyncio.to_thread(self._execute, query, params)


class _Acquire:
    def __init__(self, pool):
        self.pool = pool
        self.raw = None

    async def __aenter__(self):
        self.raw = sqlite3.connect(self.pool.path, timeout=10, check_same_thread=False)
        self.raw.row_factory = sqlite3.Row
        self.raw.execute("PRAGMA busy_timeout=10000")
        self.raw.execute("PRAGMA foreign_keys=ON")
        return SQLiteConnection(self.raw)

    async def __aexit__(self, exc_type, *_):
        if exc_type:
            self.raw.rollback()
        else:
            self.raw.commit()
        self.raw.close()
        return False


class SQLitePool:
    def __init__(self, path):
        self.path = path

    def acquire(self):
        return _Acquire(self)

    async def close(self):
        """Called on app shutdown. Nothing to release: each acquire() opens
        and closes its own connection."""
