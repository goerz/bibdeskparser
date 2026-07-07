# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "Pillow",
# ]
# ///
"""Turn a PDF into minimal-size single-page test fixture.

Keeps only the first page, rasterizes it to a low-resolution
grayscale JPEG, and stamps a diagonal watermark across it. Requires
the `qpdf` and `pdftoppm` (poppler) command line tools.

Usage:

    uv run make_test_pdf.py INPUT.pdf [-o OUTPUT.pdf] [--dpi DPI]
                            [--quality QUALITY]

If `-o`/`--output` is omitted, INPUT.pdf is overwritten in place.
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WATERMARK_TEXT = "BibDeskParser Test Data"
DEFAULT_DPI = 50
DEFAULT_QUALITY = 10


def add_watermark(img: Image.Image) -> Image.Image:
    img = img.convert("L")
    w, h = img.size
    draw_probe = ImageDraw.Draw(img)

    font_size = max(20, w // 18)
    try:
        font = ImageFont.truetype(
            "/System/Library/Fonts/Supplemental/Arial.ttf", font_size
        )
    except OSError:
        font = ImageFont.load_default()

    bbox = draw_probe.textbbox((0, 0), WATERMARK_TEXT, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    txt_img = Image.new("L", (text_w + 20, text_h + 20), 255)
    txt_draw = ImageDraw.Draw(txt_img)
    txt_draw.text((10, 10), WATERMARK_TEXT, font=font, fill=0)
    txt_img = txt_img.rotate(45, expand=True, fillcolor=255)

    x = (w - txt_img.width) // 2
    y = (h - txt_img.height) // 2
    mask = Image.eval(txt_img, lambda p: 255 - p)
    gray_overlay = Image.new("L", txt_img.size, 128)
    img.paste(gray_overlay, (x, y), mask)

    return img


def make_test_pdf(
    src: Path,
    dst: Path,
    dpi: int = DEFAULT_DPI,
    quality: int = DEFAULT_QUALITY,
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        page1_pdf = tmp / "page1.pdf"
        subprocess.run(
            ["qpdf", str(src), "--pages", str(src), "1", "--", str(page1_pdf)],
            check=True,
        )
        raster_base = tmp / "page1"
        subprocess.run(
            [
                "pdftoppm",
                "-gray",
                "-r",
                str(dpi),
                str(page1_pdf),
                str(raster_base),
            ],
            check=True,
        )
        (raster_png,) = tmp.glob("page1-*.pgm")

        img = Image.open(raster_png)
        img = add_watermark(img)

        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp_dst = tmp / "out.pdf"
        img.save(
            tmp_dst,
            "PDF",
            resolution=float(dpi),
            quality=quality,
            optimize=True,
        )
        tmp_dst.replace(dst)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Input PDF file")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output PDF file (default: overwrite input)",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=DEFAULT_DPI,
        help=f"Rasterization resolution in DPI (default: {DEFAULT_DPI})",
    )
    parser.add_argument(
        "--quality",
        type=int,
        default=DEFAULT_QUALITY,
        help=f"JPEG quality, 1-95 (default: {DEFAULT_QUALITY})",
    )
    args = parser.parse_args()

    output = args.output or args.input
    make_test_pdf(args.input, output, dpi=args.dpi, quality=args.quality)


if __name__ == "__main__":
    sys.exit(main())
