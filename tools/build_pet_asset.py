"""Build the bundled transparent pet image from the supplied reference JPG."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from qixin.pet import prepare_pet_image  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python tools/build_pet_asset.py <reference image>")
    source = Path(sys.argv[1]).expanduser().resolve()
    destination = ROOT / "qixin" / "assets" / "pet_default.png"
    prepare_pet_image(source, destination)
    print(f"created {destination}")


if __name__ == "__main__":
    main()
