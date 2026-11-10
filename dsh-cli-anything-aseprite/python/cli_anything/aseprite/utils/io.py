"""File I/O helpers: locked JSON save (prevents concurrent write corruption).

Concurrent writers (e.g. two CLI processes autosaving the same project while
the user drags a layer-opacity slider) must never share a temp filename:
each process writes its own uniquely-named temp file, then swaps it into
place under an exclusive lock on the target path.
"""

import json
import os
import uuid
from contextlib import contextmanager
from typing import Any, Dict

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None

try:
    import msvcrt
except ImportError:  # POSIX
    msvcrt = None


@contextmanager
def _exclusive_lock(file_obj):
    """Lock a file with the platform's standard-library implementation."""
    if fcntl is not None:
        fcntl.flock(file_obj.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(file_obj.fileno(), fcntl.LOCK_UN)
        return

    if msvcrt is not None:
        # msvcrt locks a byte range starting at the current file position.
        file_obj.seek(0)
        msvcrt.locking(file_obj.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            file_obj.seek(0)
            msvcrt.locking(file_obj.fileno(), msvcrt.LK_UNLCK, 1)
        return

    # Keep saves functional on unsupported Python platforms. The unique temp
    # file still prevents writers from deleting each other's in-flight data.
    yield


def locked_save_json(path: str, data: Dict[str, Any]) -> None:
    """Atomically save JSON under an exclusive file lock (concurrency-safe)."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    # Unique temp per writer: concurrent processes can never delete each
    # other's temp file mid-write.
    tmp = "{}.{}.{}.tmp".format(path, os.getpid(), uuid.uuid4().hex[:8])
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        with open(path, "a+", encoding="utf-8") as f:
            with _exclusive_lock(f):
                with open(tmp, "r", encoding="utf-8") as src:
                    f.seek(0)
                    f.truncate()
                    f.write(src.read())
                    f.flush()
                    os.fsync(f.fileno())
    finally:
        # Only ever remove our own temp file.
        try:
            os.remove(tmp)
        except OSError:
            pass


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
