"""In-memory, per-thread conversation context so follow-up questions in a
Slack thread keep context. Intentionally not persisted: losing this on
restart is an acceptable trade-off for a single-container, no-database-server
deployment, and avoids storing potentially sensitive Q&A content at rest.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class _ThreadState:
    messages: list[dict] = field(default_factory=list)
    last_used_at: float = 0.0


class ThreadContextStore:
    def __init__(self, max_turns_per_thread: int = 20, ttl_seconds: float = 3600.0):
        self._max_turns_per_thread = max_turns_per_thread
        self._ttl_seconds = ttl_seconds
        self._threads: dict[str, _ThreadState] = {}

    def _now(self) -> float:
        return time.monotonic()

    def get_history(self, thread_key: str) -> list[dict]:
        state = self._threads.get(thread_key)
        if state is None:
            return []
        if self._now() - state.last_used_at > self._ttl_seconds:
            del self._threads[thread_key]
            return []
        return list(state.messages)

    def append_turn(self, thread_key: str, question: str, answer: str) -> None:
        state = self._threads.setdefault(thread_key, _ThreadState())
        state.messages.append({"role": "user", "content": question})
        state.messages.append({"role": "assistant", "content": answer})
        # Keep only the most recent N turns (2 messages per turn).
        max_messages = self._max_turns_per_thread * 2
        if len(state.messages) > max_messages:
            state.messages = state.messages[-max_messages:]
        state.last_used_at = self._now()

    def clear(self, thread_key: str) -> None:
        self._threads.pop(thread_key, None)
