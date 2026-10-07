"""Простой ограничитель неудачных попыток (вход, регистрация по коду).

Хранится в памяти процесса: на хостинге одно приложение — одного процесса
достаточно. Окно скользящее: считаются неудачи за последние N минут.
"""
from __future__ import annotations


import time
from collections import defaultdict, deque


class FailureLimiter:
    def __init__(self) -> None:
        self._fails: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str, window_s: float) -> deque[float]:
        q = self._fails[key]
        cutoff = time.monotonic() - window_s
        while q and q[0] < cutoff:
            q.popleft()
        return q

    def retry_after(self, key: str, limit: int, window_s: float) -> int | None:
        """Секунд до разблокировки, если лимит исчерпан; иначе None."""
        q = self._prune(key, window_s)
        if len(q) < limit:
            return None
        return max(1, int(q[0] + window_s - time.monotonic()))

    def fail(self, key: str) -> None:
        self._fails[key].append(time.monotonic())

    def reset(self, key: str) -> None:
        self._fails.pop(key, None)


limiter = FailureLimiter()
