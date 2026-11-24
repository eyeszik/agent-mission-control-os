"""Copy bounded regular input files into private media scratch directories.

Open the leaf without following symlinks, check the open descriptor rather
than a path stat, and never read more than the declared bound. This reduces
path-swap and file-growth hazards; it does not make host filesystem paths a
complete hostile-multitenant security boundary.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path


class UnsafeInput(ValueError):
    """An input could not be copied safely under its budget."""


def copy_regular_bounded(source: Path, destination: Path, *, max_bytes: int) -> int:
    if max_bytes <= 0 or not hasattr(os, "O_NOFOLLOW"):
        raise UnsafeInput("input bound or no-follow support unavailable")
    try:
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError as exc:
        raise UnsafeInput("input is unavailable or a symlink") from exc
    created = False
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise UnsafeInput("input must be a regular file")
        if info.st_size <= 0 or info.st_size > max_bytes:
            raise UnsafeInput("input byte budget exceeded or empty")
        total = 0
        with os.fdopen(fd, "rb", closefd=False) as stream:
            out = destination.open("xb")
            created = True
            with out:
                while total < info.st_size:
                    chunk = stream.read(min(1024 * 1024, info.st_size - total))
                    if not chunk:
                        raise UnsafeInput("input changed while staging")
                    out.write(chunk)
                    total += len(chunk)
                if stream.read(1):
                    raise UnsafeInput("input grew while staging")
        after = os.fstat(fd)
        if (after.st_size, after.st_mtime_ns) != (info.st_size, info.st_mtime_ns):
            raise UnsafeInput("input changed while staging")
        return total
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise
    finally:
        os.close(fd)


__all__ = ["UnsafeInput", "copy_regular_bounded"]
