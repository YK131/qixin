"""Test runner for the DSH sandbox.

tempfile.mkdtemp() creates 0o700 directories which the sandbox refuses to
write into, so every temporary path is redirected into the project with
permissive modes. The real test suite runs unmodified.
"""

from __future__ import annotations

import itertools
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCAL_TMP = HERE / ".testtmp"
LOCAL_APPDATA = HERE / ".testappdata"
for folder in (LOCAL_TMP, LOCAL_APPDATA):
    folder.mkdir(parents=True, exist_ok=True)

os.environ["TMPDIR"] = str(LOCAL_TMP)
os.environ["TEMP"] = str(LOCAL_TMP)
os.environ["TMP"] = str(LOCAL_TMP)
os.environ["LOCALAPPDATA"] = str(LOCAL_APPDATA)
tempfile.tempdir = str(LOCAL_TMP)

_counter = itertools.count(1)


def _mkdtemp(suffix: str = "", prefix: str = "tmp", dir: str | None = None) -> str:
    base = dir or tempfile.tempdir or str(LOCAL_TMP)
    path = os.path.join(base, f"{prefix}{next(_counter)}{suffix}")
    os.makedirs(path, mode=0o777, exist_ok=True)
    return path


tempfile.mkdtemp = _mkdtemp  # type: ignore[assignment]

sys.path.insert(0, str(HERE))
os.chdir(HERE)
suite = unittest.TestLoader().discover("tests")
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
