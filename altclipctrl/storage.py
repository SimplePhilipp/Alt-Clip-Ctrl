"""Preserve saved Inbetween profiles when adopting the Alt Clip Ctrl name."""
import os
from pathlib import Path
import shutil
import tempfile


def migrate_settings(target, source):
    """Copy once, byte for byte; the caller holds both default-directory locks.

    Existing Alt Clip Ctrl settings always win. Keep the original file intact,
    including invalid JSON, so startup validation can report problems without
    silently losing profiles. Publish the copy only after it is fully written.
    """
    target, source = Path(target), Path(source)
    if target.exists() or not source.is_file():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as output, source.open("rb") as original:
            shutil.copyfileobj(original, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return True
