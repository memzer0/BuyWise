"""Collapse concurrent identical operations (same search query / same product refresh) into one."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any


class SingleFlight:
    def __init__(self) -> None:
        self._inflight: dict[str, asyncio.Future] = {}

    def in_progress(self, key: str) -> bool:
        return key in self._inflight

    async def do(self, key: str, fn: Callable[[], Awaitable[Any]]) -> tuple[Any, bool]:
        """Returns (result, shared) – shared=True if this caller joined an in-flight call."""
        if key in self._inflight:
            return await asyncio.shield(self._inflight[key]), True
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._inflight[key] = fut
        try:
            result = await fn()
            fut.set_result(result)
            return result, False
        except BaseException as exc:
            fut.set_exception(exc)
            fut.exception()  # mark retrieved
            raise
        finally:
            self._inflight.pop(key, None)
