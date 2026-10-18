#!/usr/bin/env python3
"""Normal Black Row — тонкая чёрная полоска по краю картинки."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

SIDE_ALIASES = {
    "left": "left",
    "right": "right",
    "top": "top",
    "bottom": "bottom",
    "лево": "left",
    "слева": "left",
    "право": "right",
    "справа": "right",
    "верх": "top",
    "сверху": "top",
    "низ": "bottom",
    "снизу": "bottom",
}


def _black(mode: str):
    if mode == "RGBA":
        return (0, 0, 0, 255)
    if mode == "RGB":
        return (0, 0, 0)
    if mode == "LA":
        return (0, 255)
    if mode == "L":
        return 0
    if mode == "CMYK":
        return (0, 0, 0, 255)
    return (0, 0, 0)


def _drawable(image: Image.Image) -> Image.Image:
    if image.mode in {"RGB", "RGBA", "L", "LA", "CMYK"}:
        return image
    if image.mode == "P" and "transparency" in image.info:
        return image.convert("RGBA")
    if "A" in image.getbands():
        return image.convert("RGBA")
    return image.convert("RGB")


def add_black_row(image: Image.Image, side: str, width: int) -> Image.Image:
    """Добавляет непрозрачную чёрную полоску, увеличивая холст на width пикселей."""
    image = _drawable(image)
    src_w, src_h = image.size
    fill = _black(image.mode)

    if side in {"left", "right"}:
        canvas = Image.new(image.mode, (src_w + width, src_h), fill)
        origin = (width, 0) if side == "left" else (0, 0)
    else:
        canvas = Image.new(image.mode, (src_w, src_h + width), fill)
        origin = (0, width) if side == "top" else (0, 0)

    canvas.paste(image, origin)
    return canvas


FORMAT_BY_SUFFIX = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
    ".bmp": "BMP",
    ".tif": "TIFF",
    ".tiff": "TIFF",
    ".gif": "GIF",
}


def _save(image: Image.Image, path: Path, exif: bytes | None, suffix: str | None = None) -> None:
    suffix = (suffix if suffix is not None else path.suffix).lower()
    params: dict = {}
    image_format = FORMAT_BY_SUFFIX.get(suffix)

    if suffix in {".jpg", ".jpeg"}:
        if image.mode not in {"RGB", "L", "CMYK"}:
            image = image.convert("RGB")
        params["quality"] = 95
        params["subsampling"] = 0
        if exif:
            params["exif"] = exif
    elif suffix == ".webp":
        params["quality"] = 95

    image.save(path, format=image_format, **params)


def process(src: Path, side: str, width: int, dest: Path) -> None:
    with Image.open(src) as image:
        image.load()
        exif = image.info.get("exif")
        result = add_black_row(image, side, width)

    if dest.resolve() == src.resolve():
        temporary = dest.with_name(dest.name + ".nbrtmp")
        try:
            _save(result, temporary, exif, suffix=dest.suffix)
            temporary.replace(dest)
        finally:
            if temporary.exists():
                temporary.unlink()
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        _save(result, dest, exif)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="normal-black-row",
        description=(
            "Normal Black Row — добавляет тонкую чёрную полоску "
            "с одной стороны картинки и пересохраняет её."
        ),
    )
    parser.add_argument("image", type=Path, help="Путь к картинке")
    parser.add_argument(
        "--side",
        default="left",
        help="Сторона: left, right, top, bottom (по умолчанию left). "
        "Можно по-русски: лево, право, верх, низ.",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=6,
        help="Ширина полоски в пикселях (по умолчанию 6)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Куда сохранить. Без этого флага исходный файл перезаписывается.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    side_key = args.side.strip().lower()
    if side_key not in SIDE_ALIASES:
        parser.error(
            f"неизвестная сторона: {args.side}. "
            "Допустимо: left, right, top, bottom."
        )
    if args.width < 1:
        parser.error("ширина должна быть не меньше 1 пикселя")
    if not args.image.is_file():
        print(f"Файл не найден: {args.image}", file=sys.stderr)
        return 1

    dest = args.output if args.output is not None else args.image
    side = SIDE_ALIASES[side_key]
    process(args.image, side, args.width, dest)
    print(f"{args.image} -> {dest} ({side}, {args.width} px)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
