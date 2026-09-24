#!/usr/bin/env python3
"""Build transparent, lossless web-sized copies of the original truss renders.

Usage:
    python3 scripts/optimize-truss-assets.py
    python3 scripts/optimize-truss-assets.py --qa-directory /tmp/truss-web-qa

Requires Pillow with WebP support. The full-resolution PNGs remain untouched.
Both copies use the same 1152-pixel width (3x the 384-pixel display cap),
LANCZOS downsampling, and lossless WebP encoding with exact RGBA preservation.
No palette, geometry, framing, alpha, or contrast adjustments are applied.
Optional QA boards compare direct PNG downsampling (left) with the delivered
WebP (right), each at the 384-pixel on-page width on the site's dark background.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from PIL import Image, features


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "public" / "research"
DISPLAY_WIDTH = 1152
QA_WIDTH = 384


def optimize(stem: str, qa_directory: Path | None) -> tuple[int, int]:
    source_path = ASSETS / f"{stem}.png"
    destination = ASSETS / f"{stem}-display.webp"
    source_bytes = source_path.read_bytes()
    source_digest = hashlib.sha256(source_bytes).hexdigest()

    with Image.open(source_path) as source:
        source.load()
        if source.mode != "RGBA":
            raise ValueError(f"Expected RGBA source: {source_path}")
        dimensions = (
            DISPLAY_WIDTH,
            round(source.height * DISPLAY_WIDTH / source.width),
        )
        resized = source.resize(dimensions, Image.Resampling.LANCZOS)
        resized.save(destination, "WEBP", lossless=True, method=6, exact=True)

        with Image.open(destination) as delivered:
            delivered.load()
            assert delivered.mode == "RGBA"
            assert delivered.size == dimensions
            assert delivered.tobytes() == resized.tobytes(), "Lossless RGBA mismatch"
            alpha_extrema = delivered.getchannel("A").getextrema()
            assert alpha_extrema[0] == 0 and alpha_extrema[1] > 0

            if qa_directory is not None:
                qa_directory.mkdir(parents=True, exist_ok=True)
                qa_dimensions = (QA_WIDTH, round(source.height * QA_WIDTH / source.width))
                original_thumb = source.resize(qa_dimensions, Image.Resampling.LANCZOS)
                delivered_thumb = delivered.resize(qa_dimensions, Image.Resampling.LANCZOS)
                comparison = Image.new("RGBA", (QA_WIDTH * 2, qa_dimensions[1]), "#0A0A0A")
                comparison.alpha_composite(original_thumb, (0, 0))
                comparison.alpha_composite(delivered_thumb, (QA_WIDTH, 0))
                comparison.convert("RGB").save(qa_directory / f"{stem}-comparison.png")

    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == source_digest
    output_bytes = destination.stat().st_size
    print(f"{destination.relative_to(ROOT)}: {dimensions[0]} x {dimensions[1]}, "
          f"{output_bytes:,} bytes; exact RGBA match, alpha {alpha_extrema}, "
          f"source unchanged ({source_digest})")
    return len(source_bytes), output_bytes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qa-directory", type=Path)
    arguments = parser.parse_args()
    if not features.check("webp"):
        raise RuntimeError("Pillow must be installed with WebP support")
    sizes = [optimize(stem, arguments.qa_directory)
             for stem in ("tanuki-truss", "tanuki-truss-mesh")]
    original_bytes, output_bytes = map(sum, zip(*sizes))
    print(f"Total: {original_bytes:,} -> {output_bytes:,} bytes "
          f"({100 * (1 - output_bytes / original_bytes):.2f}% smaller)")


if __name__ == "__main__":
    main()
