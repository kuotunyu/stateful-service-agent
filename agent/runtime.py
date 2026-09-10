"""One web server per business database; OS releases the lock on process exit."""

import os
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def exclusive_server(database):
    path = Path(database).resolve()
    lock_path = path.with_suffix(path.suffix + ".server.lock")
    with lock_path.open("a+b") as lock:
        try:
            lock.seek(0, os.SEEK_END)
            if lock.tell() == 0:
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError(
                "Database already served by another process; use a different database or stop your own server first."
            ) from None
        # Do not remove the lock file: unlinking creates a race with new servers.
        yield
