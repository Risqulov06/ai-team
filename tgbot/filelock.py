"""Cross-platform exclusive file lock (Linux, macOS, Android/Termux and Windows).

    with locked(path):
        ...   # only one process at a time gets here

fcntl only exists on Unix, so on a Windows laptop the bot used to crash on import. This module uses
fcntl.flock where it exists and msvcrt.locking on Windows.
"""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path

try:  # Unix: Linux, macOS, Termux
    import fcntl

    def _lock(f) -> None:
        fcntl.flock(f, fcntl.LOCK_EX)

    def _unlock(f) -> None:
        fcntl.flock(f, fcntl.LOCK_UN)

except ImportError:  # Windows
    import msvcrt

    def _lock(f) -> None:
        f.seek(0)
        while True:
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)  # LK_LOCK itself retries for ~10 s
                return
            except OSError:
                time.sleep(0.2)

    def _unlock(f) -> None:
        f.seek(0)
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass


@contextmanager
def locked(path: str | os.PathLike):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as f:
        _lock(f)
        try:
            yield
        finally:
            _unlock(f)
