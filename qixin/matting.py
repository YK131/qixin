"""Automatic background removal for uploaded pet pictures.

Only Pillow and the standard library are used -- no numpy, OpenCV or rembg.
The pipeline is built for ordinary snapshots (phone photos of a wall, a desk,
a gradient backdrop) instead of studio green screens:

1.  Read any format Pillow can decode, keep the first frame, downscale huge
    files before touching a single pixel.
2.  Estimate up to four background colours from the four image borders with a
    couple of k-means passes over the border pixels, so "desk on the left,
    wall on the right" ends up as two colours instead of one average, and a
    lit gradient is spread over several anchors.  Mid-point anchors are
    interpolated between neighbouring colours, which keeps every tolerance
    tight.
3.  Score every pixel with an adaptive colour tolerance (tight for a flat
    backdrop, loose for a gradient) and flood fill the border-connected
    region that matches those colours.
4.  Turn the colour-distance score into a soft alpha ramp inside a narrow
    band around the outline, so hair and plush edges fade out instead of
    being cut with scissors.
5.  If the borders do not enclose a background at all (subject touching the
    frame) fall back to a luminance/saturation threshold plus the largest
    connected component.
6.  If the result is implausible (< 1.5% or > 99% subject) return the
    original inside a soft elliptical vignette with a shadow, so the user
    never ends up with an empty pet.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

# Upper bounds that keep a stray 100 MP photo from freezing the UI thread.
MAX_SOURCE_BYTES = 40 * 1024 * 1024
MAX_SOURCE_PIXELS = 24_000_000
# Everything after decoding happens at this longest side (the pet master is
# 512 px, so 720 keeps a comfortable margin without slow Python loops).
MAX_WORK_SIDE = 720

MAX_BACKGROUND_COLORS = 4

# Colour-distance (Chebyshev, 0..255) tolerances around a background colour.
BACKGROUND_TOL_MIN = 12
BACKGROUND_TOL_MAX = 110
# Score offset: a pixel whose score is <= gate matches a background colour.
BACKGROUND_GATE = 64

MIN_BACKGROUND_SHARE = 0.08
MAX_BACKGROUND_SHARE = 0.92
MIN_SUBJECT_SHARE = 0.015
MAX_SUBJECT_SHARE = 0.99

# Output contract of ``normalize``: a 512 px canvas with bottom padding.
PET_CANVAS = 512
PET_PADDING = 38

# 0 -> 0, 1 -> 255, used to expand a packed 0/1 mask into an "L" image.
_BYTE_TABLE = bytes([0, 255]) + bytes(254)

_TOP, _BOTTOM, _LEFT, _RIGHT = 0, 1, 2, 3


def _clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


def _cheb(left: Sequence[int], right: Sequence[int]) -> int:
    """Chebyshev distance: cheap, and monotone with the euclidean one."""

    return max(
        abs(int(left[0]) - int(right[0])),
        abs(int(left[1]) - int(right[1])),
        abs(int(left[2]) - int(right[2])),
    )


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_image(source: str | Path) -> Image.Image:
    """Open *any* Pillow-readable picture as an RGBA image.

    The format is sniffed from the file content, never from the extension.
    Multi-frame files (GIF/WebP/TIFF) keep their first frame, EXIF rotation is
    honoured, and very large files are decoded/thumbnailed down to a workable
    size before matting.
    """

    path = Path(source)
    try:
        byte_size = path.stat().st_size
    except OSError as exc:
        raise ValueError("找不到这张图片，请重新选择。") from exc

    try:
        with Image.open(path) as opened:
            try:
                opened.seek(0)
            except (EOFError, ValueError):
                pass
            # JPEG/MPO can decode straight to a smaller size: much cheaper than
            # decoding 40 MP and scaling afterwards.
            if (
                byte_size > MAX_SOURCE_BYTES
                or opened.width * opened.height > MAX_SOURCE_PIXELS
            ):
                try:
                    opened.draft("RGB", (MAX_WORK_SIDE * 3, MAX_WORK_SIDE * 3))
                except (AttributeError, ValueError, OSError):
                    pass
            frame = ImageOps.exif_transpose(opened)
            frame.load()
            image = frame.convert("RGBA")
    except Image.DecompressionBombError as exc:
        raise ValueError(
            "这张图片的像素太大了，请先压缩后再上传。"
        ) from exc
    except (OSError, ValueError, SyntaxError, MemoryError) as exc:
        raise ValueError(
            "无法读取这张图片。任意格式图片都可以（PNG/JPEG/WebP/BMP/GIF/TIFF 等），"
            "我们会自动去背景。"
        ) from exc

    if max(image.size) > MAX_WORK_SIDE:
        image.thumbnail((MAX_WORK_SIDE, MAX_WORK_SIDE), Image.Resampling.LANCZOS)
    return image


# ---------------------------------------------------------------------------
# Border sampling
# ---------------------------------------------------------------------------


def _border_samples(
    rgb: Image.Image,
) -> list[tuple[tuple[int, int, int], int]]:
    """Every border pixel together with the edge it belongs to."""

    width, height = rgb.size
    pixels = rgb.load()
    samples: list[tuple[tuple[int, int, int], int]] = []
    for x in range(width):
        samples.append((pixels[x, 0], _TOP))
        samples.append((pixels[x, height - 1], _BOTTOM))
    for y in range(height):
        samples.append((pixels[0, y], _LEFT))
        samples.append((pixels[width - 1, y], _RIGHT))
    return samples


def _weighted_median(
    colors: Sequence[Sequence[int]],
    weights: Sequence[int],
) -> tuple[int, int, int]:
    channels: list[int] = []
    for index in range(3):
        pairs = sorted(
            (int(color[index]), int(weight))
            for color, weight in zip(colors, weights)
        )
        total = sum(weight for _, weight in pairs) or 1
        running = 0
        chosen = pairs[-1][0]
        for value, weight in pairs:
            running += weight
            if running * 2 >= total:
                chosen = value
                break
        channels.append(chosen)
    return channels[0], channels[1], channels[2]


def _seed_representatives(
    colors: Sequence[Sequence[int]],
    count: int,
) -> list[tuple[int, int, int]]:
    """Median colour plus farthest-point seeds: spreads over gradients."""

    if not colors:
        return []
    seeds: list[tuple[int, int, int]] = [
        _weighted_median(colors, [1] * len(colors))
    ]
    while len(seeds) < count:
        best: tuple[int, int, int] | None = None
        best_distance = 0
        for color in colors:
            distance = min(_cheb(color, seed) for seed in seeds)
            if distance > best_distance:
                best_distance = distance
                best = (int(color[0]), int(color[1]), int(color[2]))
        if best is None or best_distance == 0:
            break
        seeds.append(best)
    return seeds


def _assign(
    samples: Sequence[tuple[tuple[int, int, int], int]],
    representatives: Sequence[Sequence[int]],
) -> list[list[tuple[tuple[int, int, int], int]]]:
    groups: list[list[tuple[tuple[int, int, int], int]]] = [
        [] for _ in representatives
    ]
    for color, edge in samples:
        best_index = 0
        best_distance = 10**6
        for index, representative in enumerate(representatives):
            delta = max(
                abs(color[0] - representative[0]),
                abs(color[1] - representative[1]),
                abs(color[2] - representative[2]),
            )
            if delta < best_distance:
                best_distance = delta
                best_index = index
        groups[best_index].append((color, edge))
    return groups


def _background_colors(rgb: Image.Image) -> list[tuple[tuple[int, int, int], int]]:
    """Return `[((r, g, b), tolerance), ...]` estimated from the borders.

    Border pixels are clustered with a few k-means iterations (median
    representatives, farthest-point seeding).  A flat backdrop collapses into
    one cluster with a tiny tolerance, while a gradient or a "desk on the
    left, wall on the right" photo is spread over up to four clusters whose
    tolerances are the 95th percentile of their own spread.
    """

    samples = _border_samples(rgb)
    if not samples:
        return []
    width, height = rgb.size
    edge_lengths = {_TOP: width, _BOTTOM: width, _LEFT: height, _RIGHT: height}
    colors = [color for color, _ in samples]

    representatives: list[tuple[int, int, int]] = _seed_representatives(
        colors, MAX_BACKGROUND_COLORS
    )
    groups = _assign(samples, representatives)
    for _ in range(5):
        refined: list[tuple[int, int, int]] = []
        for group, representative in zip(groups, representatives):
            if not group:
                refined.append(tuple(representative))
                continue
            refined.append(_weighted_median([color for color, _ in group], [1] * len(group)))
        if refined == representatives:
            break
        representatives = refined
        groups = _assign(samples, representatives)

    total = float(len(samples))
    clusters: list[dict[str, Any]] = []
    for representative, group in zip(representatives, groups):
        if not group:
            continue
        per_edge: dict[int, int] = {}
        for _, edge in group:
            per_edge[edge] = per_edge.get(edge, 0) + 1
        edges = set(per_edge)
        coverage = max(per_edge[edge] / edge_lengths[edge] for edge in edges)
        distances = sorted(_cheb(color, representative) for color, _ in group)
        high = distances[min(len(distances) - 1, int(len(distances) * 0.95))]
        clusters.append(
            {
                "color": tuple(representative),
                "edges": edges,
                "coverage": coverage,
                "count": len(group),
                "tolerance": int(
                    _clamp(
                        BACKGROUND_TOL_MIN + 1.0 * high,
                        BACKGROUND_TOL_MIN,
                        BACKGROUND_TOL_MAX,
                    )
                ),
            }
        )

    # A colour that only shows up along one border is usually the subject
    # itself touching the frame, not the backdrop -- unless it fills that
    # entire border, which means it is a backdrop strip (e.g. a wall above a
    # subject that runs off the bottom of the photo).
    kept = [
        cluster
        for cluster in clusters
        if len(cluster["edges"]) >= 2 or cluster["coverage"] >= 0.8
    ]
    if not kept:
        kept = clusters
    big = [
        cluster for cluster in kept if cluster["count"] / total >= 0.02
    ] or kept[:1]
    big.sort(key=lambda cluster: -int(cluster["count"]))
    big = big[:MAX_BACKGROUND_COLORS]
    anchors = [
        (cluster["color"], int(cluster["tolerance"]))  # type: ignore[arg-type]
        for cluster in big
    ]
    return _fill_gradient_gaps(anchors)


def _fill_gradient_gaps(
    anchors: list[tuple[tuple[int, int, int], int]],
) -> list[tuple[tuple[int, int, int], int]]:
    """Interpolate between neighbouring background colours.

    A camera gradient is a line through colour space, not a handful of balls:
    dropping a mid-point anchor between two close representatives lets every
    anchor keep a *tight* tolerance, which is what stops a beige subject from
    being swallowed by a beige wall.
    """

    ordered = sorted(anchors, key=lambda item: item[0][0] + item[0][1] + item[0][2])
    result = list(ordered)
    for (first, _), (second, _) in zip(ordered, ordered[1:]):
        gap = _cheb(first, second)
        if not 24 <= gap <= 140:
            continue
        middle = (
            round((first[0] + second[0]) / 2),
            round((first[1] + second[1]) / 2),
            round((first[2] + second[2]) / 2),
        )
        if any(_cheb(middle, anchor) <= 8 for anchor, _ in result):
            continue
        result.append((middle, int(_clamp(0.32 * gap, BACKGROUND_TOL_MIN, 28))))
    return result


# ---------------------------------------------------------------------------
# Colour scoring and masks
# ---------------------------------------------------------------------------


def _excess_image(
    rgb: Image.Image,
    backgrounds: Sequence[tuple[tuple[int, int, int], int]],
) -> Image.Image:
    """Per-pixel distance to the closest background colour, offset by the gate.

    ``0..64`` means "matches a background colour", values above the gate are
    progressively more foreground-like.  Chebyshev distance is used so that
    the whole map can be built with Pillow's C-level channel arithmetic.
    """

    width, height = rgb.size
    red, green, blue = rgb.split()
    excess: Image.Image | None = None
    for (bg_red, bg_green, bg_blue), tolerance in backgrounds:
        difference = ImageChops.lighter(
            ImageChops.lighter(
                ImageChops.difference(red, Image.new("L", (width, height), bg_red)),
                ImageChops.difference(green, Image.new("L", (width, height), bg_green)),
            ),
            ImageChops.difference(blue, Image.new("L", (width, height), bg_blue)),
        )
        lookup = [
            int(_clamp(value - tolerance + BACKGROUND_GATE, 0, 255))
            for value in range(256)
        ]
        scored = difference.point(lookup)
        excess = scored if excess is None else ImageChops.darker(excess, scored)
    assert excess is not None
    return excess


def _flood_background(
    similar: bytes,
    width: int,
    height: int,
) -> tuple[bytearray, float]:
    """Flood fill the border-connected pixels flagged in *similar*."""

    mask = bytearray(width * height)
    stack: list[int] = []
    last = height - 1
    for x in range(width):
        for index in (x, last * width + x):
            if similar[index] and not mask[index]:
                mask[index] = 1
                stack.append(index)
    right = width - 1
    for y in range(height):
        base = y * width
        for index in (base, base + right):
            if similar[index] and not mask[index]:
                mask[index] = 1
                stack.append(index)

    while stack:
        index = stack.pop()
        x = index % width
        if x:
            neighbour = index - 1
            if similar[neighbour] and not mask[neighbour]:
                mask[neighbour] = 1
                stack.append(neighbour)
        if x < right:
            neighbour = index + 1
            if similar[neighbour] and not mask[neighbour]:
                mask[neighbour] = 1
                stack.append(neighbour)
        if index >= width:
            neighbour = index - width
            if similar[neighbour] and not mask[neighbour]:
                mask[neighbour] = 1
                stack.append(neighbour)
        if index + width < width * height:
            neighbour = index + width
            if similar[neighbour] and not mask[neighbour]:
                mask[neighbour] = 1
                stack.append(neighbour)

    filled = mask.count(1)
    return mask, filled / float(width * height)


def _largest_component(binary: bytes, width: int, height: int) -> bytes | None:
    """Keep the biggest blob plus any blob at least 15% of its size."""

    size = width * height
    right = width - 1
    seen = bytearray(size)
    components: list[list[int]] = []
    for start in range(size):
        if not binary[start] or seen[start]:
            continue
        seen[start] = 1
        stack = [start]
        members = [start]
        while stack:
            index = stack.pop()
            x = index % width
            if x:
                neighbour = index - 1
                if binary[neighbour] and not seen[neighbour]:
                    seen[neighbour] = 1
                    members.append(neighbour)
                    stack.append(neighbour)
            if x < right:
                neighbour = index + 1
                if binary[neighbour] and not seen[neighbour]:
                    seen[neighbour] = 1
                    members.append(neighbour)
                    stack.append(neighbour)
            if index >= width:
                neighbour = index - width
                if binary[neighbour] and not seen[neighbour]:
                    seen[neighbour] = 1
                    members.append(neighbour)
                    stack.append(neighbour)
            if index + width < size:
                neighbour = index + width
                if binary[neighbour] and not seen[neighbour]:
                    seen[neighbour] = 1
                    members.append(neighbour)
                    stack.append(neighbour)
        components.append(members)

    if not components:
        return None
    components.sort(key=len, reverse=True)
    largest = len(components[0])
    if largest < 16:
        return None
    keep = [blob for blob in components if len(blob) >= max(16, largest * 0.15)]
    out = bytearray(size)
    for blob in keep:
        for index in blob:
            out[index] = 255
    return bytes(out)


def _fill_holes(mask: Image.Image) -> Image.Image:
    """Fill enclosed holes: everything the border flood fill cannot reach."""

    width, height = mask.size
    outside, _ = _flood_background(ImageChops.invert(mask).tobytes(), width, height)
    outside_image = Image.frombytes("L", (width, height), bytes(outside.translate(_BYTE_TABLE)))
    holes = ImageChops.multiply(
        ImageChops.invert(outside_image),
        ImageChops.invert(mask),
    )
    return ImageChops.lighter(mask, holes)


def _border_brightness(rgb: Image.Image) -> tuple[float, float, float, float]:
    width, height = rgb.size
    gray = rgb.convert("L").load()
    saturation = rgb.convert("HSV").getchannel("S").load()
    luminances: list[int] = []
    saturations: list[int] = []
    for x in range(width):
        luminances.extend((gray[x, 0], gray[x, height - 1]))
        saturations.extend((saturation[x, 0], saturation[x, height - 1]))
    for y in range(height):
        luminances.extend((gray[0, y], gray[width - 1, y]))
        saturations.extend((saturation[0, y], saturation[width - 1, y]))

    def mean(values: list[int]) -> float:
        return sum(values) / len(values) if values else 0.0

    def deviation(values: list[int], anchor: float) -> float:
        if not values:
            return 0.0
        return (sum((value - anchor) ** 2 for value in values) / len(values)) ** 0.5

    mean_l = mean(luminances)
    mean_s = mean(saturations)
    return mean_l, deviation(luminances, mean_l), mean_s, deviation(saturations, mean_s)


def _threshold_subject(
    rgb: Image.Image,
    excess: Image.Image,
    tolerance: float,
) -> Image.Image | None:
    """Luminance/saturation threshold + largest component (no border backdrop)."""

    width, height = rgb.size
    mean_l, sd_l, mean_s, sd_s = _border_brightness(rgb)
    gray = rgb.convert("L")
    saturation = rgb.convert("HSV").getchannel("S")
    flat_l = Image.new("L", (width, height), int(round(mean_l)))
    flat_s = Image.new("L", (width, height), int(round(mean_s)))

    for relax in (1.0, 0.66, 0.4):
        l_threshold = max(10.0, relax * (1.5 * sd_l + 14.0))
        s_threshold = max(12.0, relax * (1.5 * sd_s + 16.0))
        color_gate = BACKGROUND_GATE + round(relax * max(8.0, tolerance * 0.4))

        luminance = ImageChops.difference(gray, flat_l).point(
            lambda value, limit=l_threshold: 255 if value > limit else 0
        )
        chroma = ImageChops.difference(saturation, flat_s).point(
            lambda value, limit=s_threshold: 255 if value > limit else 0
        )
        color = excess.point(
            lambda value, gate=color_gate: 255 if value > gate else 0
        )
        candidate = ImageChops.lighter(ImageChops.lighter(luminance, chroma), color)

        blob = _largest_component(candidate.tobytes(), width, height)
        if blob is None:
            continue

        mask = Image.frombytes("L", (width, height), blob)
        mask = mask.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5))
        mask = _fill_holes(mask)
        share = _subject_share(mask)
        if share >= 0.02:
            return mask
    return None


def _subject_share(alpha: Image.Image) -> float:
    histogram = alpha.histogram()
    total = alpha.width * alpha.height
    if not total:
        return 0.0
    return sum(histogram[129:]) / float(total)


def _plausible(alpha: Image.Image) -> bool:
    """Is this cut-out believable?  Guards against rings and stray slivers."""

    share = _subject_share(alpha)
    if share < MIN_SUBJECT_SHARE or share > MAX_SUBJECT_SHARE:
        return False
    bbox = alpha.point(lambda value: 255 if value > 12 else 0).getbbox()
    if bbox is None:
        return False
    box_area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
    if box_area <= 0:
        return False
    pixels = share * alpha.width * alpha.height
    # A pet fills a good part of its own bounding box; a thin ring or a few
    # leftover border slivers do not.
    return pixels / float(box_area) >= 0.18


def _soft_alpha(mask: Image.Image, excess: Image.Image) -> Image.Image:
    """Turn the binary mask into an alpha ramp driven by colour distance.

    The ramp is normalised against the 85th percentile of the subject's own
    distance, so a fringe pixel that is half background ends up at roughly
    half alpha.  A 5 px eroded interior is forced back to 255 so a subject
    that happens to share the backdrop colour keeps its body.
    """

    width, height = mask.size
    subject_pixels = mask.histogram()[255]
    level = BACKGROUND_GATE
    if subject_pixels:
        interior = Image.composite(
            excess,
            Image.new("L", (width, height), 0),
            mask,
        )
        counts = interior.histogram()
        wanted = max(1, int(subject_pixels * 0.15))
        running = 0
        for value in range(255, -1, -1):
            running += counts[value]
            if running >= wanted:
                level = value
                break

    ramp = int(_clamp(level - BACKGROUND_GATE, 20, 191))
    lookup = [
        0
        if value <= BACKGROUND_GATE
        else 255
        if value >= BACKGROUND_GATE + ramp
        else round(255 * (value - BACKGROUND_GATE) / ramp)
        for value in range(256)
    ]
    gradient = excess.point(lookup)

    reach = 5 if min(width, height) > 240 else 3
    keep = 11 if min(width, height) > 240 else 7
    dilated = mask.filter(ImageFilter.MaxFilter(reach))
    eroded = mask.filter(ImageFilter.MinFilter(keep))
    # Outside the dilated mask the ramp is suppressed: background shadows two
    # pixels away must not become an opaque grey rim.
    restricted = ImageChops.multiply(gradient, dilated)
    alpha = ImageChops.lighter(eroded, restricted)
    return alpha.filter(ImageFilter.GaussianBlur(1.0))


def _extract_alpha(rgb: Image.Image) -> Image.Image | None:
    width, height = rgb.size
    backgrounds = _background_colors(rgb)
    excess = _excess_image(rgb, backgrounds)
    tolerance = sum(tolerance for _, tolerance in backgrounds) / len(backgrounds)

    similar = excess.point(
        lambda value: 255 if value <= BACKGROUND_GATE else 0
    ).tobytes()
    background, share = _flood_background(similar, width, height)

    if share >= MAX_BACKGROUND_SHARE:
        # The flood swallowed the whole frame: the subject touches every
        # border and no backdrop is separable.  Hand the picture back as-is
        # (with the shadow vignette) instead of cutting the pet away.
        return None

    if share >= MIN_BACKGROUND_SHARE:
        packed = Image.frombytes(
            "L",
            (width, height),
            bytes(background.translate(_BYTE_TABLE)),
        )
        subject = ImageChops.invert(packed)
    else:
        # The subject touches (or fills) the frame: fall back to thresholds
        # and keep the largest blob instead of trusting the border flood.
        subject = _threshold_subject(rgb, excess, tolerance)
        if subject is None:
            return None

    alpha = _soft_alpha(subject, excess)
    if _plausible(alpha):
        return alpha

    # The flood result looks like a ring or a sliver; give the threshold
    # strategy one chance before handing over to the shadow fallback.
    if share >= MIN_BACKGROUND_SHARE:
        alternate = _threshold_subject(rgb, excess, tolerance)
        if alternate is not None:
            alternate_alpha = _soft_alpha(alternate, excess)
            if _plausible(alternate_alpha):
                return alternate_alpha
    return None


# ---------------------------------------------------------------------------
# Fallbacks and composition helpers
# ---------------------------------------------------------------------------


def _as_rgba(image: Image.Image) -> Image.Image:
    rgba = image if image.mode == "RGBA" else image.convert("RGBA")
    if rgba is image:
        return rgba.copy()
    return rgba


def _has_transparency(rgba: Image.Image) -> bool:
    histogram = rgba.getchannel("A").histogram()
    total = rgba.width * rgba.height
    if not total:
        return False
    return sum(histogram[:250]) / float(total) > 0.01


def _feather_only(rgba: Image.Image) -> Image.Image:
    alpha = rgba.getchannel("A").filter(ImageFilter.GaussianBlur(0.8))
    result = rgba.copy()
    result.putalpha(alpha)
    return result


def _alpha_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    alpha = image.getchannel("A").point(lambda value: 255 if value > 12 else 0)
    return alpha.getbbox()


def _fallback_with_shadow(image: Image.Image) -> Image.Image:
    """Original picture inside a soft ellipse, with a shadow underneath.

    Used when matting cannot produce a believable silhouette, so the pet is
    never blank and the upload still "works".
    """

    width, height = image.size
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    shadow_inset_x = max(2, round(width * 0.10))
    shadow_inset_y = max(2, round(height * 0.13))
    blur = max(1.5, min(width, height) * 0.045)

    shadow_mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(shadow_mask).ellipse(
        (
            shadow_inset_x,
            shadow_inset_y + round(height * 0.05),
            width - shadow_inset_x,
            height - shadow_inset_y + round(height * 0.05),
        ),
        fill=170,
    )
    shadow_mask = shadow_mask.filter(ImageFilter.GaussianBlur(blur))
    shadow = Image.new("RGBA", (width, height), (26, 30, 27, 0))
    shadow.putalpha(shadow_mask)
    canvas.alpha_composite(shadow)

    vignette = Image.new("L", (width, height), 0)
    ImageDraw.Draw(vignette).ellipse(
        (
            round(width * 0.03),
            round(height * 0.02),
            round(width * 0.97),
            round(height * 0.98),
        ),
        fill=255,
    )
    vignette = vignette.filter(
        ImageFilter.GaussianBlur(max(1.5, min(width, height) * 0.012))
    )
    photo = _as_rgba(image)
    photo.putalpha(ImageChops.multiply(photo.getchannel("A"), vignette))
    canvas.alpha_composite(photo)
    return canvas


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def matte(image: Image.Image) -> Image.Image:
    """Return *image* with a transparent background.

    Images that already carry real transparency are only feathered.  Anything
    else goes through the border flood fill (or the threshold fallback), and a
    result that looks broken is swapped for the original-plus-shadow vignette
    so the caller always gets something usable.
    """

    rgba = _as_rgba(image)
    if _has_transparency(rgba):
        return _feather_only(rgba)

    work = rgba.convert("RGB")
    if max(work.size) > MAX_WORK_SIDE:
        work.thumbnail((MAX_WORK_SIDE, MAX_WORK_SIDE), Image.Resampling.LANCZOS)

    alpha = _extract_alpha(work)
    if alpha is None:
        return _fallback_with_shadow(work)

    share = _subject_share(alpha)
    if share < MIN_SUBJECT_SHARE or share > MAX_SUBJECT_SHARE:
        return _fallback_with_shadow(work)

    result = work.convert("RGBA")
    result.putalpha(alpha)
    return result


def fallback(image: Image.Image) -> Image.Image:
    """Public entry point for the "keep the original, add a soft vignette" path."""

    return _fallback_with_shadow(_as_rgba(image))


def normalize(image: Image.Image) -> Image.Image:
    """Crop to the alpha bounding box and fit a 512 px, bottom-aligned canvas."""

    rgba = _as_rgba(image)
    bbox = _alpha_bbox(rgba)
    if bbox is None:
        return Image.new("RGBA", (PET_CANVAS, PET_CANVAS), (0, 0, 0, 0))

    subject = rgba.crop(bbox)
    available = PET_CANVAS - PET_PADDING * 2
    scale = min(available / subject.width, available / subject.height)
    target = (
        max(1, round(subject.width * scale)),
        max(1, round(subject.height * scale)),
    )
    if target != subject.size:
        subject = subject.resize(target, Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (PET_CANVAS, PET_CANVAS), (0, 0, 0, 0))
    x = (PET_CANVAS - subject.width) // 2
    y = PET_CANVAS - PET_PADDING - subject.height
    canvas.alpha_composite(subject, (x, y))

    alpha = canvas.getchannel("A").filter(ImageFilter.GaussianBlur(1.0))
    canvas.putalpha(alpha)
    return canvas
