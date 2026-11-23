from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from qixin.appearance import prepare_background, prepare_icon
from qixin.theme import COLORS, VisualKit


class AppearanceTests(unittest.TestCase):
    def test_glass_card_has_rounded_translucent_face_and_no_clipped_shadow(self) -> None:
        with patch("qixin.theme.ImageTk.PhotoImage", side_effect=lambda image, **kwargs: image):
            kit = VisualKit(None, 1.25)
            for hovered in (False, True):
                with self.subTest(hovered=hovered):
                    card = kit.card_face(1200, 105, 40, COLORS["glass"], hover=hovered)
                    alpha = card.getchannel("A")
                    w, h = card.size
                    for edge in ((0, 0, w, 1), (0, h - 1, w, h),
                                 (0, 0, 1, h), (w - 1, 0, w, h)):
                        self.assertIsNone(alpha.crop(edge).getbbox())
                    pad = kit.shadow_pad()
                    self.assertLess(alpha.getpixel((pad + 4, pad + 4)), 50)
                    self.assertLess(alpha.getpixel((w // 2, pad + 85)),
                                    alpha.getpixel((w // 2, pad + 12)))

    def test_background_and_icon_are_normalized(self) -> None:
        with tempfile.TemporaryDirectory(prefix="qixin-appearance-") as temp:
            temp_path = Path(temp)
            source = temp_path / "source.png"
            image = Image.new("RGB", (640, 320), "#DCE9DF")
            ImageDraw.Draw(image).ellipse((220, 40, 430, 280), fill="#D8A365")
            image.save(source)
            background = temp_path / "background.png"
            icon = temp_path / "icon.png"
            with (
                patch("qixin.appearance.BACKGROUND_PATH", background),
                patch("qixin.appearance.ICON_PATH", icon),
            ):
                prepare_background(source)
                prepare_icon(source)

            with Image.open(background) as result:
                self.assertEqual(result.size, (2560, 1600))
                self.assertEqual(result.mode, "RGB")
            with Image.open(icon) as result:
                self.assertEqual(result.size, (512, 512))
                self.assertEqual(result.getchannel("A").getpixel((0, 0)), 0)
                self.assertGreater(result.getchannel("A").getpixel((256, 256)), 245)


if __name__ == "__main__":
    unittest.main()
