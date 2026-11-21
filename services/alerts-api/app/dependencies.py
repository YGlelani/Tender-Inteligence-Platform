from typing import Annotated

from fastapi import Depends, HTTPException, Request

from .sqlite_pool import SQLitePool


def get_pool(request: Request) -> SQLitePool:
    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        raise HTTPException(503, "Database is not initialized")
    return pool


Pool = Annotated[SQLitePool, Depends(get_pool)]
