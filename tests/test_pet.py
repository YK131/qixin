"""Tests for the desktop pet: pendulum maths, bundled art and uploads.

``tempfile`` is avoided on purpose: inside the DSH Windows sandbox its 0o700
directories cannot be cleaned up, so a plain project-local ``.tmpx`` folder is
used instead.  The assertions themselves are unchanged.
"""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from qixin.pet import DEFAULT_PET_IMAGE, pendulum_angle, prepare_pet_image

ROOT = Path(__file__).resolve().parents[1]
TMP_ROOT = ROOT / ".tmpx"


def workdir(name: str) -> Path:
    path = TMP_ROOT / f"pet-{name}"
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


def corners(image: Image.Image) -> list[int]:
    alpha = image.getchannel("A")
    width, height = image.size
    return [
        alpha.getpixel((0, 0)),
        alpha.getpixel((width - 1, 0)),
        alpha.getpixel((0, height - 1)),
        alpha.getpixel((width - 1, height - 1)),
    ]


def opaque_share(image: Image.Image) -> float:
    histogram = image.getchannel("A").histogram()
    return sum(histogram[129:]) / float(image.width * image.height)


def circle_on_white(size: int = 640) -> Image.Image:
    image = Image.new("RGB", (size, size), "white")
    ImageDraw.Draw(image).ellipse(
        (size * 0.28, size * 0.16, size * 0.72, size * 0.82),
        fill="#1E2A24",
    )
    return image


class PetImageTests(unittest.TestCase):
    def test_pendulum_reaches_45_degrees_and_slows_at_edges(self) -> None:
        self.assertAlmostEqual(pendulum_angle(0.0), 0.0, places=5)
        self.assertAlmostEqual(pendulum_angle(0.25), 45.0, places=5)
        self.assertAlmostEqual(pendulum_angle(0.5), 0.0, places=5)
        self.assertAlmostEqual(pendulum_angle(0.75), -45.0, places=5)
        self.assertAlmostEqual(pendulum_angle(1.0), 0.0, places=5)
        self.assertGreater(
            abs(pendulum_angle(0.03) - pendulum_angle(0.01)),
            abs(pendulum_angle(0.26) - pendulum_angle(0.24)),
        )

    def test_bundled_pet_is_transparent_png(self) -> None:
        self.assertTrue(DEFAULT_PET_IMAGE.exists())
        with Image.open(DEFAULT_PET_IMAGE) as image:
            self.assertEqual(image.size, (512, 512))
            self.assertEqual(image.mode, "RGBA")
            alpha = image.getchannel("A")
            self.assertLess(alpha.getextrema()[0], 10)
            self.assertGreater(alpha.getextrema()[1], 245)

    def test_uploaded_png_is_cropped_and_normalized(self) -> None:
        temp = workdir(self._testMethodName)
        try:
            source = temp / "custom.png"
            target = temp / "normalized.png"
            image = Image.new("RGBA", (180, 120), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.ellipse((40, 15, 140, 110), fill="#7B9D65")
            image.save(source)

            prepare_pet_image(source, target)

            with Image.open(target) as result:
                self.assertEqual(result.size, (512, 512))
                alpha = result.getchannel("A")
                self.assertEqual(alpha.getpixel((0, 0)), 0)
                self.assertGreater(alpha.getextrema()[1], 245)
        finally:
            shutil.rmtree(temp, ignore_errors=True)

    def test_opaque_light_background_is_removed(self) -> None:
        temp = workdir(self._testMethodName)
        try:
            source = temp / "opaque.png"
            target = temp / "normalized.png"
            image = Image.new("RGB", (160, 160), "white")
            draw = ImageDraw.Draw(image)
            draw.ellipse((30, 20, 130, 140), fill="#E7C875")
            image.save(source)

            prepare_pet_image(source, target)

            with Image.open(target) as result:
                alpha = result.getchannel("A")
                self.assertEqual(alpha.getpixel((0, 0)), 0)
                self.assertGreater(alpha.getextrema()[1], 245)
        finally:
            shutil.rmtree(temp, ignore_errors=True)

    def test_gradient_photo_background_is_removed(self) -> None:
        """A phone photo with a lit, gradient wall must not keep a grey band."""

        temp = workdir(self._testMethodName)
        try:
            source = temp / "gradient.png"
            target = temp / "normalized.png"
            image = Image.new("RGB", (640, 640))
            draw = ImageDraw.Draw(image)
            for y in range(640):
                value = min(255, 46 + int(y * 0.42))
                draw.line((0, y, 640, y), fill=(value, value, value))
            draw.ellipse((220, 160, 460, 470), fill="#F2D58A")
            image.save(source)

            prepare_pet_image(source, target)

            with Image.open(target) as result:
                self.assertEqual(result.mode, "RGBA")
                self.assertEqual(corners(result), [0, 0, 0, 0])
                self.assertGreater(result.getchannel("A").getpixel((256, 256)), 200)
                self.assertLess(opaque_share(result), 0.85)
        finally:
            shutil.rmtree(temp, ignore_errors=True)

    def test_empty_picture_still_produces_a_visible_pet(self) -> None:
        temp = workdir(self._testMethodName)
        try:
            source = temp / "blank.png"
            target = temp / "normalized.png"
            Image.new("RGB", (500, 500), "white").save(source)

            prepare_pet_image(source, target)

            with Image.open(target) as result:
                alpha = result.getchannel("A")
                self.assertGreater(alpha.getextrema()[1], 200)
                self.assertGreater(opaque_share(result), 0.3)
        finally:
            shutil.rmtree(temp, ignore_errors=True)


class PreparePetImageFormatTests(unittest.TestCase):
    """Any Pillow-readable format can become a pet."""

    def setUp(self) -> None:
        self.tmp = workdir(self._testMethodName)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def assert_is_pet(self, target: Path) -> None:
        self.assertTrue(target.exists())
        with Image.open(target) as result:
            self.assertEqual(result.format, "PNG")
            self.assertEqual(result.size, (512, 512))
            self.assertEqual(result.mode, "RGBA")
            self.assertEqual(corners(result), [0, 0, 0, 0])
            alpha = result.getchannel("A")
            self.assertGreater(alpha.getpixel((256, 256)), 200)
            bbox = alpha.point(lambda value: 255 if value > 12 else 0).getbbox()
            assert bbox is not None
            self.assertGreaterEqual(bbox[3], 468)
            self.assertLessEqual(bbox[3], 477)
            share = opaque_share(result)
            self.assertGreater(share, 0.15)
            self.assertLess(share, 0.9)

    def test_png_jpeg_bmp_webp_gif_tiff(self) -> None:
        base = circle_on_white()
        cases = {
            "input.png": (None, {}),
            "input.jpg": ("JPEG", {"quality": 92}),
            "input.bmp": ("BMP", {}),
            "input.webp": ("WEBP", {"quality": 90}),
            "input.gif": ("GIF", {}),
            "input.tiff": ("TIFF", {}),
        }
        for name, (fmt, options) in cases.items():
            with self.subTest(name=name):
                source = self.tmp / name
                if fmt:
                    base.save(source, fmt, **options)
                else:
                    base.save(source)
                target = self.tmp / f"{name}.out.png"
                prepare_pet_image(source, target)
                self.assert_is_pet(target)

    def test_extension_does_not_decide_the_format(self) -> None:
        source = self.tmp / "really-png.jpg"
        circle_on_white().save(source, "PNG")
        target = self.tmp / "out.png"
        prepare_pet_image(source, target)
        self.assert_is_pet(target)

    def test_transparent_png_keeps_its_alpha(self) -> None:
        source = self.tmp / "alpha.png"
        image = Image.new("RGBA", (600, 600), (0, 0, 0, 0))
        ImageDraw.Draw(image).ellipse((120, 100, 480, 500), fill=(123, 157, 101, 255))
        image.save(source)
        target = self.tmp / "out.png"
        prepare_pet_image(source, target)
        self.assert_is_pet(target)
        with Image.open(target) as result:
            red, green, blue, alpha = result.getpixel((256, 300))
            self.assertGreater(alpha, 200)
            self.assertLess(abs(red - 123), 8)
            self.assertLess(abs(green - 157), 8)
            self.assertLess(abs(blue - 101), 8)

    def test_animated_gif_uses_the_first_frame(self) -> None:
        source = self.tmp / "animated.gif"
        first = circle_on_white(320)
        second = Image.new("RGB", (320, 320), "#2F6FD0")
        ImageDraw.Draw(second).rectangle((60, 60, 260, 260), fill="#D94F3D")
        first.save(source, save_all=True, append_images=[second], duration=120, loop=0)

        target = self.tmp / "out.png"
        prepare_pet_image(source, target)

        with Image.open(target) as result:
            red, green, blue, alpha = result.getpixel((256, 256))
            self.assertGreater(alpha, 200)
            self.assertLess(max(red, green, blue), 120, "second GIF frame leaked in")

    def test_unreadable_file_mentions_any_format_in_the_error(self) -> None:
        source = self.tmp / "broken.jpg"
        source.write_bytes(b"\x00\x01\x02 not an image")
        with self.assertRaises(ValueError) as caught:
            prepare_pet_image(source, self.tmp / "out.png")
        message = str(caught.exception)
        self.assertIn("任意格式图片都可以", message)
        self.assertIn("去背景", message)


if __name__ == "__main__":
    unittest.main()
