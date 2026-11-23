"""Write user data and caches without truncating the previous file."""
import os
import tempfile
from pathlib import Path


def write_text_atomic(path, content):
    target = Path(path)
    temp = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, delete=False)
    try:
        with temp:
            temp.write(content)
            temp.flush()
            os.fsync(temp.fileno())
        os.replace(temp.name, target)
    finally:
        Path(temp.name).unlink(missing_ok=True)
