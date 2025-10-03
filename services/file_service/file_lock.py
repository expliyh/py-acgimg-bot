import asyncio
import aiorwlock

dict_lock = aiorwlock.RWLock()
file_locks = {}


def get_dick_lock() -> aiorwlock.RWLock:
    return dict_lock


def get_lock(lock_name: str) -> tuple[aiorwlock.RWLock, asyncio.Lock]:
    """Return a tuple containing the global dict lock and a per-file lock."""

    lock = file_locks.get(lock_name)
    if lock is None:
        lock = asyncio.Lock()
        file_locks[lock_name] = lock

    return dict_lock, lock


def del_lock(lock_name: str) -> None:
    # 注意自行处理 dict_lock
    file_locks.pop(lock_name)
