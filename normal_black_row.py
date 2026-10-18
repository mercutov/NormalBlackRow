#!/usr/bin/env python3
"""Normal Black Row — чёрная полоска и кадрирование картинки."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
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


save_image = _save


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


FRAME_HEIGHT = 1440
CUSTOM_WIDTH_MIN = 600
CUSTOM_WIDTH_MAX = 2000

PRESETS: tuple[tuple[int, int], ...] = (
    (845, FRAME_HEIGHT),
    (1280, FRAME_HEIGHT),
    (1690, FRAME_HEIGHT),
)

REALESRGAN_URL = (
    "https://github.com/xinntao/Real-ESRGAN/releases/download/"
    "v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip"
)
REALESRGAN_MODEL = "realesrgan-x4plus"
REALESRGAN_SCALE = 4


def content_box(target_w: int, target_h: int, side: str, bar: int) -> tuple[int, int, int, int]:
    """Область фото внутри кадра: x, y, ширина, высота. Полоска входит в размер кадра."""
    if bar < 0:
        raise ValueError("ширина полоски не может быть отрицательной")
    if side in {"left", "right"}:
        if bar >= target_w:
            raise ValueError("полоска не помещается в ширину кадра")
        if side == "left":
            return bar, 0, target_w - bar, target_h
        return 0, 0, target_w - bar, target_h
    if side in {"top", "bottom"}:
        if bar >= target_h:
            raise ValueError("полоска не помещается в высоту кадра")
        if side == "top":
            return 0, bar, target_w, target_h - bar
        return 0, 0, target_w, target_h - bar
    raise ValueError(f"неизвестная сторона: {side}")


def minimum_scale(img_w: int, img_h: int, content_w: int, content_h: int) -> float:
    """Минимальный масштаб, при котором картинка ещё закрывает область фото."""
    return max(content_w / img_w, content_h / img_h)


def maximum_scale(content_w: int, content_h: int, floor: float) -> float:
    """Дальше приближать некуда: в кадре остаётся хотя бы 32 исходных пикселя."""
    return max(floor, min(content_w, content_h) / 32)


def framed_crop(
    img_w: int,
    img_h: int,
    content_w: int,
    content_h: int,
    scale: float,
    cx: float,
    cy: float,
) -> tuple[float, float, float, float, float, float, float]:
    """Возвращает x, y, w, h фрагмента и фактические центр и масштаб после ограничения."""
    low = minimum_scale(img_w, img_h, content_w, content_h)
    high = maximum_scale(content_w, content_h, low)
    scale = min(max(scale, low), high)
    crop_w = min(content_w / scale, float(img_w))
    crop_h = min(content_h / scale, float(img_h))
    x = min(max(0.0, cx - crop_w / 2), img_w - crop_w)
    y = min(max(0.0, cy - crop_h / 2), img_h - crop_h)
    return x, y, crop_w, crop_h, x + crop_w / 2, y + crop_h / 2, scale


def _clamp_box(box: tuple[float, float, float, float], img_w: int, img_h: int) -> tuple[float, float, float, float]:
    x, y, w, h = box
    x = min(max(0.0, x), max(0.0, img_w - 1.0))
    y = min(max(0.0, y), max(0.0, img_h - 1.0))
    w = min(max(1.0, w), img_w - x)
    h = min(max(1.0, h), img_h - y)
    return x, y, w, h


def sample(
    image: Image.Image,
    box: tuple[float, float, float, float],
    out_w: int,
    out_h: int,
    resample: Image.Resampling,
) -> Image.Image:
    image = _drawable(image)
    x, y, w, h = _clamp_box(box, image.width, image.height)
    return image.resize((out_w, out_h), resample, box=(x, y, x + w, y + h))


def compose(photo: Image.Image, target_w: int, target_h: int, side: str, bar: int) -> Image.Image:
    origin_x, origin_y, content_w, content_h = content_box(target_w, target_h, side, bar)
    if photo.size != (content_w, content_h):
        photo = photo.resize((content_w, content_h), Image.Resampling.LANCZOS)
    canvas = Image.new(photo.mode, (target_w, target_h), _black(photo.mode))
    if "A" in photo.getbands():
        canvas.paste(photo, (origin_x, origin_y), photo)
    else:
        canvas.paste(photo, (origin_x, origin_y))
    return canvas


def render_framed(
    image: Image.Image,
    target_w: int,
    target_h: int,
    side: str,
    bar: int,
    scale: float,
    cx: float,
    cy: float,
    resample: Image.Resampling = Image.Resampling.LANCZOS,
) -> Image.Image:
    _, _, content_w, content_h = content_box(target_w, target_h, side, bar)
    x, y, crop_w, crop_h, _, _, _ = framed_crop(
        image.width, image.height, content_w, content_h, scale, cx, cy
    )
    photo = sample(image, (x, y, crop_w, crop_h), content_w, content_h, resample)
    return compose(photo, target_w, target_h, side, bar)


APP_REPO = "mercutov/NormalBlackRow"


def app_dir() -> Path:
    return Path(__file__).resolve().parent


def parse_version(text: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in text.strip().split("."):
        if not piece.isdigit():
            raise ValueError(f"непонятная версия: {text.strip()}")
        parts.append(int(piece))
    if not parts:
        raise ValueError("пустая версия")
    return tuple(parts)


def local_version() -> tuple[int, ...]:
    path = app_dir() / "VERSION"
    if not path.is_file():
        return (0,)
    return parse_version(path.read_text(encoding="utf-8"))


def fetch_remote_version() -> tuple[int, ...] | None:
    url = f"https://raw.githubusercontent.com/{APP_REPO}/master/VERSION"
    request = urllib.request.Request(url, headers={"User-Agent": "NormalBlackRow"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return parse_version(response.read().decode("utf-8"))
    except Exception:
        return None


def update_available() -> str | None:
    """Версия на GitHub, если она новее локальной. Иначе None."""
    remote = fetch_remote_version()
    if remote is None or remote <= local_version():
        return None
    return ".".join(str(part) for part in remote)


def _copy_tree(source: Path, dest: Path) -> None:
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if any(part == "__pycache__" or part.endswith(".pyc") for part in relative.parts):
            continue
        target = dest / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def apply_update(on_progress=None) -> None:
    """Подтягивает master. В клоне git это pull, в установленной копии — архив с GitHub."""
    root = app_dir()
    if (root / ".git").is_dir():
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        completed = subprocess.run(
            ["git", "pull", "--ff-only", "origin", "master"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=flags,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(detail or "git pull не удался")
        return

    url = f"https://github.com/{APP_REPO}/archive/refs/heads/master.zip"
    with tempfile.TemporaryDirectory(prefix="nbr-update-") as folder:
        folder_path = Path(folder)
        archive_path = folder_path / "master.zip"
        request = urllib.request.Request(url, headers={"User-Agent": "NormalBlackRow"})
        with urllib.request.urlopen(request, timeout=60) as response, archive_path.open("wb") as handle:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                done += len(chunk)
                if on_progress is not None:
                    on_progress(done, total)
        unpack = folder_path / "src"
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(unpack)
        sources = [path for path in unpack.iterdir() if path.is_dir()]
        if len(sources) != 1:
            raise RuntimeError("В архиве обновления не одна папка")
        _copy_tree(sources[0], root)


def tools_dir() -> Path:
    return app_dir() / "tools" / "realesrgan"


def find_realesrgan() -> Path | None:
    root = tools_dir()
    if root.exists():
        found = next(root.rglob("realesrgan-ncnn-vulkan.exe"), None)
        if found is not None:
            return found
    on_path = shutil.which("realesrgan-ncnn-vulkan.exe")
    if on_path:
        return Path(on_path)
    return None


def download_realesrgan(on_progress=None) -> Path:
    """Запасной путь, если в копии нет модели. Обычная установка уже содержит её."""
    existing = find_realesrgan()
    if existing is not None:
        return existing

    root = tools_dir()
    root.mkdir(parents=True, exist_ok=True)
    zip_path = root / "download.zip"
    request = urllib.request.Request(REALESRGAN_URL, headers={"User-Agent": "NormalBlackRow"})
    with urllib.request.urlopen(request, timeout=60) as response, zip_path.open("wb") as handle:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = response.read(256 * 1024)
            if not chunk:
                break
            handle.write(chunk)
            done += len(chunk)
            if on_progress is not None:
                on_progress(done, total)

    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(root)
    zip_path.unlink(missing_ok=True)

    found = find_realesrgan()
    if found is None:
        raise RuntimeError("В архиве не нашёлся realesrgan-ncnn-vulkan.exe")
    return found


def upscale_crop(
    image: Image.Image,
    box: tuple[float, float, float, float],
    out_w: int,
    out_h: int,
    exe: Path,
) -> Image.Image:
    """Увеличивает выбранный фрагмент Real-ESRGAN x4 и приводит к точному размеру фото."""
    image = _drawable(image)
    if image.mode not in {"RGB", "L"}:
        image = image.convert("RGB")

    x, y, w, h = _clamp_box(box, image.width, image.height)
    pad = 32
    left = max(0, int(x) - pad)
    top = max(0, int(y) - pad)
    right = min(image.width, int(x + w + 0.999) + pad)
    bottom = min(image.height, int(y + h + 0.999) + pad)
    region = image.crop((left, top, right, bottom))

    with tempfile.TemporaryDirectory(prefix="nbr-") as folder:
        folder_path = Path(folder)
        source = folder_path / "in.png"
        destination = folder_path / "out.png"
        region.save(source, format="PNG")
        command = [
            str(exe),
            "-i",
            str(source),
            "-o",
            str(destination),
            "-n",
            REALESRGAN_MODEL,
            "-s",
            str(REALESRGAN_SCALE),
            "-m",
            str(exe.parent / "models"),
            "-f",
            "png",
        ]
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        completed = subprocess.run(
            command,
            cwd=exe.parent,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=flags,
        )
        if completed.returncode != 0 or not destination.exists():
            detail = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(detail or f"Real-ESRGAN завершился с кодом {completed.returncode}")

        with Image.open(destination) as upscaled:
            upscaled.load()
            grown = upscaled.copy()

    factor_x = grown.width / region.width
    factor_y = grown.height / region.height
    sample_box = (
        (x - left) * factor_x,
        (y - top) * factor_y,
        w * factor_x,
        h * factor_y,
    )
    return sample(grown, sample_box, out_w, out_h, Image.Resampling.LANCZOS)


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
