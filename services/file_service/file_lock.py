import asyncio
import aiorwlock

dict_lock = aiorwlock.RWLock()
file_locks = {}


def get_dick_lock() -> aiorwlock.RWLock:
    return dict_lock


def get_lock(lock_name: str) -> tuple[aiorwlock.RWLock, asyncio.Lock]:
    if lock_name in file_locks:
        return file_locks[lock_name]
    else:
        lock = asyncio.Lock()
        file_locks[lock_name] = lock
        return dict_lock, lock


def del_lock(lock_name: str) -> None:
    # 注意自行处理 dict_lock
    file_locks.pop(lock_name)
