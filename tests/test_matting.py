"""Tests for the automatic background removal used by the desktop pet.

The suite builds every fixture with Pillow, so it needs no binary assets and
no network.  ``tempfile`` is avoided on purpose: inside the DSH Windows
sandbox its 0o700 directories cannot be cleaned up, so a plain project-local
``.tmpx`` folder is used instead (the test semantics are unchanged).
"""

from __future__ import annotations

import colorsys
import random
import shutil
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw, ImageFilter

from qixin import matting
from qixin.matting import fallback, load_image, matte, normalize

ROOT = Path(__file__).resolve().parents[1]
TMP_ROOT = ROOT / ".tmpx"
SIZE = 640


def workdir(name: str) -> Path:
    path = TMP_ROOT / f"matting-{name}"
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def white_circle() -> Image.Image:
    image = Image.new("RGB", (SIZE, SIZE), "white")
    ImageDraw.Draw(image).ellipse((200, 130, 440, 510), fill="#1E2A24")
    return image


def blue_square() -> Image.Image:
    image = Image.new("RGB", (SIZE, SIZE), "#2F6FD0")
    ImageDraw.Draw(image).rectangle((180, 180, 460, 460), fill="#D94F3D")
    return image


def gray_gradient() -> Image.Image:
    image = Image.new("RGB", (SIZE, SIZE))
    draw = ImageDraw.Draw(image)
    for y in range(SIZE):
        value = 46 + int(y * 0.42)
        value = min(255, value)
        draw.line((0, y, SIZE, y), fill=(value, value, value))
    draw.ellipse((220, 160, 460, 470), fill="#F2D58A")
    return image


def quadrant_desk() -> Image.Image:
    """Top-left desk, top-right wall, bottom-left paper, bottom-right cloth."""

    image = Image.new("RGB", (SIZE, SIZE), "#8A7A63")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, SIZE // 2, SIZE // 2), fill="#6E5B44")
    draw.rectangle((SIZE // 2, 0, SIZE, SIZE // 2), fill="#9E9484")
    draw.rectangle((0, SIZE // 2, SIZE // 2, SIZE), fill="#B7AE9C")
    draw.rectangle((SIZE // 2, SIZE // 2, SIZE, SIZE), fill="#5D6B70")
    draw.ellipse((200, 150, 440, 480), fill="#E7C875")
    return image


def soft_hair() -> Image.Image:
    image = Image.new("RGB", (SIZE, SIZE), "#EDE7DC")
    halo = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(halo).ellipse((220, 170, 420, 450), fill=255)
    halo = halo.filter(ImageFilter.GaussianBlur(12))
    image.paste(Image.new("RGB", (SIZE, SIZE), "#8C5A3C"), (0, 0), halo)
    return image


def alpha_cutout() -> Image.Image:
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(image).ellipse((170, 120, 450, 500), fill=(123, 157, 101, 255))
    return image


def touching_bottom() -> Image.Image:
    image = Image.new("RGB", (SIZE, SIZE), "#F4F1EA")
    ImageDraw.Draw(image).ellipse((240, 320, 470, 700), fill="#7B9D65")
    return image


def fills_frame() -> Image.Image:
    image = Image.new("RGB", (SIZE, SIZE), "#3A4A3F")
    draw = ImageDraw.Draw(image)
    for y in range(0, SIZE, 3):
        draw.line((0, y, SIZE, y), fill="#3D4E42")
    return image


def blank_white() -> Image.Image:
    return Image.new("RGB", (SIZE, SIZE), "white")


def bokeh() -> Image.Image:
    rng = random.Random(11)
    image = Image.new("RGB", (SIZE, SIZE), "#D8D2C4")
    draw = ImageDraw.Draw(image)
    for _ in range(60):
        hue = rng.random()
        red, green, blue = colorsys.hsv_to_rgb(hue, 0.75, 0.9)
        radius = rng.randint(40, 130)
        x = rng.randint(-60, SIZE)
        y = rng.randint(-60, SIZE)
        draw.ellipse(
            (x, y, x + radius, y + radius),
            fill=(int(red * 255), int(green * 255), int(blue * 255)),
        )
    image = image.filter(ImageFilter.GaussianBlur(14))
    ImageDraw.Draw(image).ellipse((240, 190, 430, 470), fill="#F0CE6A")
    return image


def photo_like() -> Image.Image:
    """A pink-ish subject on a noisy, slightly lit wall (JPEG-style photo)."""

    rng = random.Random(5)
    image = Image.new("RGB", (SIZE, SIZE))
    pixels = image.load()
    for y in range(SIZE):
        for x in range(SIZE):
            base = 170 + int(28 * (y / SIZE)) + rng.randint(-12, 12)
            pixels[x, y] = (base, base - 5, base - 12)
    ImageDraw.Draw(image).ellipse((210, 160, 450, 480), fill="#D9603F")
    return image


def checkerboard(size: tuple[int, int], cell: int = 16) -> Image.Image:
    board = Image.new("RGB", size, "#E9E6E0")
    draw = ImageDraw.Draw(board)
    for y in range(0, size[1], cell):
        for x in range(0, size[0], cell):
            if (x // cell + y // cell) % 2:
                draw.rectangle((x, y, x + cell - 1, y + cell - 1), fill="#C7C3BB")
    return board


def opaque_share(image: Image.Image) -> float:
    alpha = image.getchannel("A") if image.mode == "RGBA" else image
    histogram = alpha.histogram()
    return sum(histogram[129:]) / float(image.width * image.height)


def semi_transparent_pixels(image: Image.Image) -> int:
    histogram = image.getchannel("A").histogram()
    return sum(histogram[1:254])


def corners(image: Image.Image) -> list[int]:
    alpha = image.getchannel("A")
    width, height = image.size
    return [
        alpha.getpixel((0, 0)),
        alpha.getpixel((width - 1, 0)),
        alpha.getpixel((0, height - 1)),
        alpha.getpixel((width - 1, height - 1)),
    ]


# ---------------------------------------------------------------------------
# matte()
# ---------------------------------------------------------------------------


class MatteSyntheticTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = workdir(self._testMethodName)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def assert_cutout(self, source: Image.Image, min_share: float = 0.05) -> Image.Image:
        cut = matte(source)
        self.assertEqual(cut.mode, "RGBA")
        self.assertEqual(cut.size, source.size)
        alpha = cut.getchannel("A")
        width, height = cut.size
        for value in corners(cut):
            self.assertLess(value, 14, "background corner survived")
        self.assertGreater(alpha.getpixel((width // 2, height // 2)), 200)
        share = opaque_share(cut)
        self.assertGreater(share, min_share)
        self.assertLess(share, 0.95)
        return cut

    def test_white_background_black_circle(self) -> None:
        self.assert_cutout(white_circle())

    def test_blue_background_red_square(self) -> None:
        cut = self.assert_cutout(blue_square())
        self.assertEqual(cut.getpixel((cut.width // 2, cut.height // 2))[:3], (217, 79, 61))

    def test_gray_gradient_background_has_no_leftover_band(self) -> None:
        cut = self.assert_cutout(gray_gradient())
        alpha = cut.getchannel("A")
        # Every row above the subject must be fully transparent: a tolerance
        # gap in the gradient used to leave an opaque horizontal stripe.
        for y in range(0, 120, 10):
            row = [alpha.getpixel((x, y)) for x in range(0, cut.width, 16)]
            self.assertTrue(all(value < 16 for value in row), f"row {y} kept background")
        # The ellipse covers roughly 0.4 of the frame; allow generous slack but
        # reject a full-width stripe (which used to inflate the area).
        self.assertLess(opaque_share(cut), 0.55)

    def test_quadrant_desk_photo_uses_several_background_colours(self) -> None:
        cut = self.assert_cutout(quadrant_desk())
        alpha = cut.getchannel("A")
        for x, y in ((80, 80), (560, 80), (80, 560), (560, 560)):
            self.assertLess(alpha.getpixel((x, y)), 16)
        self.assertGreater(alpha.getpixel((320, 320)), 200)

    def test_soft_edges_keep_a_partial_alpha_ramp(self) -> None:
        cut = matte(soft_hair())
        self.assertGreater(
            semi_transparent_pixels(cut),
            500,
            "soft hair edge was cut with scissors instead of feathered",
        )
        self.assertLess(min(corners(cut)), 14)

    def test_existing_alpha_is_reused(self) -> None:
        source = alpha_cutout()
        cut = matte(source)
        self.assertEqual(cut.size, source.size)
        alpha = cut.getchannel("A")
        self.assertEqual(alpha.getpixel((0, 0)), 0)
        self.assertGreater(alpha.getpixel((320, 320)), 250)
        # RGB must stay untouched: only the alpha edges are feathered.
        self.assertEqual(cut.getpixel((320, 320))[:3], (123, 157, 101))

    def test_subject_touching_the_bottom_edge_is_kept(self) -> None:
        cut = matte(touching_bottom())
        alpha = cut.getchannel("A")
        self.assertGreater(opaque_share(cut), 0.1)
        self.assertGreaterEqual(alpha.point(lambda v: 255 if v > 128 else 0).getbbox()[3], 636)

    def test_subject_filling_the_frame_falls_back_to_a_vignette(self) -> None:
        cut = matte(fills_frame())
        alpha = cut.getchannel("A")
        self.assertEqual(alpha.getextrema()[1], 255, "fallback must not be empty")
        self.assertGreater(opaque_share(cut), 0.4)
        self.assertLess(min(corners(cut)), 14)

    def test_blank_image_never_returns_an_empty_pet(self) -> None:
        cut = matte(blank_white())
        self.assertEqual(cut.mode, "RGBA")
        self.assertGreater(cut.getchannel("A").getextrema()[1], 200)

    def test_busy_background_does_not_yield_a_ring(self) -> None:
        cut = matte(bokeh())
        alpha = cut.getchannel("A")
        # A ring or sliver would keep a thin frame with a huge bounding box.
        self.assertGreater(opaque_share(cut), 0.3)
        self.assertLess(min(corners(cut)), 14)
        self.assertIsNotNone(alpha.getbbox())

    def test_noisy_photo_background_is_removed(self) -> None:
        cut = matte(photo_like())
        alpha = cut.getchannel("A")
        self.assertLess(alpha.getpixel((20, 20)), 14)
        self.assertGreater(alpha.getpixel((320, 320)), 200)
        self.assertLess(opaque_share(cut), 0.55)

    def test_large_image_is_downscaled_before_matching(self) -> None:
        source = Image.new("RGB", (3000, 2000), "#DDD6C6")
        ImageDraw.Draw(source).ellipse((900, 500, 2100, 1700), fill="#4E6B58")
        cut = matte(source)
        self.assertLessEqual(max(cut.size), matting.MAX_WORK_SIDE)
        self.assertGreater(cut.width, cut.height)
        self.assertGreater(opaque_share(cut), 0.1)

    def test_fallback_keeps_the_picture_visible(self) -> None:
        source = photo_like()
        cut = fallback(source)
        self.assertEqual(cut.size, source.size)
        self.assertEqual(cut.mode, "RGBA")
        self.assertGreater(cut.getchannel("A").getextrema()[1], 200)
        self.assertLess(min(corners(cut)), 14)


class NormalizeTests(unittest.TestCase):
    def test_bottom_alignment_and_canvas_size(self) -> None:
        source = white_circle()
        canvas = normalize(matte(source))
        self.assertEqual(canvas.size, (512, 512))
        self.assertEqual(canvas.mode, "RGBA")
        bbox = canvas.getchannel("A").point(lambda v: 255 if v > 12 else 0).getbbox()
        assert bbox is not None
        self.assertGreaterEqual(bbox[3], 470)
        self.assertLessEqual(bbox[3], 476)
        # Horizontally centred: equal margins left and right.
        self.assertLessEqual(abs(bbox[0] - (512 - bbox[2])), 4)
        self.assertGreater(bbox[2] - bbox[0], 200)
        self.assertEqual(corners(canvas), [0, 0, 0, 0])

    def test_alpha_edges_are_feathered(self) -> None:
        canvas = normalize(matte(white_circle()))
        histogram = canvas.getchannel("A").histogram()
        self.assertGreater(sum(histogram[1:254]), 200)

    def test_transparent_input_normalizes_to_something(self) -> None:
        canvas = normalize(Image.new("RGBA", (32, 32), (0, 0, 0, 0)))
        self.assertEqual(canvas.getchannel("A").getextrema(), (0, 0))


# ---------------------------------------------------------------------------
# load_image()
# ---------------------------------------------------------------------------


class LoadImageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = workdir(self._testMethodName)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_format_is_sniffed_from_content_not_extension(self) -> None:
        source = white_circle()
        disguised = self.tmp / "actually-a-png.jpg"
        source.save(disguised, "PNG")
        image = load_image(disguised)
        self.assertEqual(image.mode, "RGBA")
        self.assertEqual(image.size, (SIZE, SIZE))

    def test_every_common_format_opens(self) -> None:
        base = white_circle()
        cases = {
            "sample.png": None,
            "sample.jpg": {"quality": 92},
            "sample.bmp": None,
            "sample.webp": {"quality": 90},
            "sample.tif": None,
            "sample.ico": {"sizes": [(256, 256)]},
        }
        for name, options in cases.items():
            with self.subTest(name=name):
                path = self.tmp / name
                if options:
                    base.save(path, **options)
                else:
                    base.save(path)
                image = load_image(path)
                self.assertEqual(image.mode, "RGBA")
                self.assertGreater(image.width, 0)

    def test_multiframe_gif_keeps_the_first_frame(self) -> None:
        first = Image.new("RGB", (240, 240), "white")
        ImageDraw.Draw(first).ellipse((60, 60, 180, 180), fill="#E7C875")
        second = Image.new("RGB", (240, 240), "#2F6FD0")
        ImageDraw.Draw(second).rectangle((60, 60, 180, 180), fill="#D94F3D")
        path = self.tmp / "animated.gif"
        first.save(path, save_all=True, append_images=[second], duration=120, loop=0)

        image = load_image(path)
        self.assertEqual(image.size, (240, 240))
        red, green, blue = image.convert("RGB").getpixel((120, 120))
        self.assertGreater(red, 200)
        self.assertGreater(green, 150)
        self.assertLess(blue, 160)

    def test_huge_file_is_compressed_before_decoding(self) -> None:
        path = self.tmp / "big.png"
        Image.new("RGB", (SIZE, SIZE), "#DDD6C6").save(path)
        with mock.patch.object(matting, "MAX_SOURCE_BYTES", 16), mock.patch.object(
            matting, "MAX_SOURCE_PIXELS", 64
        ):
            image = load_image(path)
        self.assertLessEqual(max(image.size), matting.MAX_WORK_SIDE)
        self.assertEqual(image.mode, "RGBA")

    def test_unreadable_file_raises_a_friendly_error(self) -> None:
        broken = self.tmp / "broken.png"
        broken.write_bytes(b"this is not an image at all")
        with self.assertRaises(ValueError) as caught:
            load_image(broken)
        self.assertIn("任意格式图片都可以", str(caught.exception))

    def test_missing_file_raises_a_friendly_error(self) -> None:
        with self.assertRaises(ValueError):
            load_image(self.tmp / "nope.png")


if __name__ == "__main__":
    unittest.main()
