"Storage 统一生成 RFC 9562 UUIDv7，不把业务键编码进数据库主键"

from __future__ import annotations

import os
import secrets
import threading
import time
from uuid import UUID

_lock = threading.Lock()
_last_ms = -1
_random = 0
_RANDOM_MASK = (1 << 74) - 1
_TAIL_MASK = (1 << 62) - 1


def new_task_id() -> str:
    "task 短 ID 独立生成，不能截取 UUIDv7 的时间前缀"
    return secrets.token_hex(4)


def new_id() -> str:
    "生成时间有序 UUIDv7；同进程同毫秒及时钟回退时保持严格递增"
    global _last_ms, _random
    with _lock:
        timestamp = time.time_ns() // 1_000_000
        if timestamp > _last_ms:
            _random = secrets.randbits(74)
        else:
            timestamp = _last_ms
            if _random == _RANDOM_MASK:
                timestamp += 1
                _random = secrets.randbits(74)
            else:
                _random += 1
        if not 0 <= timestamp < 1 << 48:
            raise OverflowError("UUIDv7 时间超出 48 位毫秒范围")
        _last_ms = timestamp
        value = (timestamp << 80) | (7 << 76) | ((_random >> 62) << 64) | (2 << 62) | (_random & _TAIL_MASK)
        return str(UUID(int=value))


def _after_fork() -> None:
    "子进程不能继承父进程的锁状态或递增随机段"
    global _lock, _last_ms, _random
    _lock = threading.Lock()
    _last_ms, _random = -1, 0


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork)
