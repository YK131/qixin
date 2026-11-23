from __future__ import annotations

import os
import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from qixin.db import Store
from qixin.theme import reset_font_family
from qixin.typography import FontLibrary


@unittest.skipUnless(sys.platform == "win32", "Windows font registration only")
class FontLibraryTests(unittest.TestCase):
    def test_system_font_can_be_registered_and_reset(self) -> None:
        font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "Deng.ttf"
        self.assertTrue(font_path.exists())
        root = tk.Tk()
        root.withdraw()
        try:
            with tempfile.TemporaryDirectory(prefix="qixin-font-") as temp:
                store = Store(Path(temp) / "test.db")
                try:
                    with patch("qixin.typography.app_data_dir", return_value=Path(temp)):
                        library = FontLibrary(root, store)
                        family = library.upload(font_path)
                        self.assertTrue(family)
                        self.assertIn(
                            family,
                            {str(value) for value in root.tk.call("font", "families")},
                        )
                        self.assertTrue(Path(store.get_setting("font_path")).exists())
                        library.reset()
                        self.assertEqual(store.get_setting("font_path"), "")
                finally:
                    store.close()
        finally:
            reset_font_family()
            root.destroy()


if __name__ == "__main__":
    unittest.main()
