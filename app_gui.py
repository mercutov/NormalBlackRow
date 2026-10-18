#!/usr/bin/env python3
"""Окно кадрирования Normal Black Row."""

from __future__ import annotations

import math
import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from PIL import Image, ImageOps, ImageTk

import normal_black_row as nbr

BG = "#1f1f1f"
FG = "#f3f3f3"
MUTED = "#bdbdbd"
BTN = "#3a3a3a"
CANVAS = "#242424"
PREVIEW_MAX = 2200

SIDES = (
    ("слева", "left"),
    ("справа", "right"),
    ("сверху", "top"),
    ("снизу", "bottom"),
)
SIDE_BY_LABEL = dict(SIDES)


def _fix_tcl() -> None:
    """Подсказывает Tk, где лежит init.tcl, если python.exe стоит отдельно от библиотек."""
    install = Path(tk.__file__).resolve().parents[2]
    tcl = install / "tcl" / "tcl8.6"
    tk_lib = install / "tcl" / "tk8.6"
    if "TCL_LIBRARY" not in os.environ and (tcl / "init.tcl").is_file():
        os.environ["TCL_LIBRARY"] = str(tcl)
    if "TK_LIBRARY" not in os.environ and (tk_lib / "tk.tcl").is_file():
        os.environ["TK_LIBRARY"] = str(tk_lib)


def _dpi() -> None:
    if sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _preview_source(image: Image.Image) -> tuple[Image.Image, float]:
    image = nbr._drawable(image)
    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGB")
    longest = max(image.size)
    if longest <= PREVIEW_MAX:
        return image, 1.0
    ratio = PREVIEW_MAX / longest
    resized = image.resize(
        (max(1, int(image.width * ratio)), max(1, int(image.height * ratio))),
        Image.Resampling.BOX,
    )
    return resized, ratio


class CropApp(tk.Tk):
    def __init__(self) -> None:
        _fix_tcl()
        super().__init__()
        self.title("Normal Black Row")
        self.configure(bg=BG)
        self.minsize(880, 720)
        self.geometry("1080x940")

        self.image: Image.Image | None = None
        self.preview: Image.Image | None = None
        self.preview_ratio = 1.0
        self.source_path: Path | None = None
        self.preset = nbr.PRESETS[0]
        self.custom = False
        self.side = "left"
        self.bar = 6
        self.scale = 1.0
        self.cx = 0.0
        self.cy = 0.0
        self.photo_screen: tuple[float, float, float, float] | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self._drag: tuple[float, float, float, float] | None = None
        self._redraw_job: str | None = None
        self._sharp_job: str | None = None
        self._want_sharp = False
        self._syncing = False
        self._busy = False

        self.bar_var = tk.IntVar(value=6)
        self.custom_width_var = tk.IntVar(value=1080)
        self.side_label = tk.StringVar(value="слева")
        self.upscale_var = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Откройте картинку.")

        self._build()
        self.bar_var.trace_add("write", self._on_bar)
        self._style_presets()
        self._refresh_model_button()
        self.bind("<Left>", lambda event: self._nudge(event, -1, 0))
        self.bind("<Right>", lambda event: self._nudge(event, 1, 0))
        self.bind("<Up>", lambda event: self._nudge(event, 0, -1))
        self.bind("<Down>", lambda event: self._nudge(event, 0, 1))
        self.after(800, self._check_update_async)

    def _build(self) -> None:
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=12, pady=(12, 4))

        self._button(top, "Открыть", self.choose_file).pack(side="left")
        self.preset_buttons: dict[tuple[int, int], tk.Button] = {}
        for width, height in nbr.PRESETS:
            button = self._button(top, f"{width}×{height}", lambda w=width, h=height: self.choose_preset(w, h))
            button.pack(side="left", padx=(8, 0))
            self.preset_buttons[(width, height)] = button
        self.custom_btn = self._button(top, "Своя", self._apply_custom)
        self.custom_btn.pack(side="left", padx=(8, 0))
        self.custom_width = tk.Spinbox(
            top,
            from_=nbr.CUSTOM_WIDTH_MIN,
            to=nbr.CUSTOM_WIDTH_MAX,
            width=6,
            textvariable=self.custom_width_var,
            command=self._apply_custom,
            bg="#2c2c2c",
            fg=FG,
            buttonbackground=BTN,
            insertbackground=FG,
            relief="flat",
            font=("Segoe UI", 10),
        )
        self.custom_width.pack(side="left", padx=(8, 0))
        self.custom_width.bind("<Return>", self._apply_custom)
        self.custom_width.bind("<KeyRelease>", self._apply_custom)
        tk.Label(top, text="×1440", bg=BG, fg=FG, font=("Segoe UI", 10)).pack(side="left", padx=(4, 0))

        options = tk.Frame(self, bg=BG)
        options.pack(fill="x", padx=12, pady=4)
        tk.Label(options, text="Полоска", bg=BG, fg=FG, font=("Segoe UI", 10)).pack(side="left")
        side_menu = tk.OptionMenu(options, self.side_label, *[label for label, _ in SIDES], command=self._on_side)
        side_menu.configure(bg=BTN, fg=FG, activebackground="#4a4a4a", highlightthickness=0, relief="flat")
        side_menu["menu"].configure(bg=BTN, fg=FG, font=("Segoe UI", 10))
        side_menu.pack(side="left", padx=(8, 12))
        tk.Spinbox(
            options,
            from_=0,
            to=200,
            width=5,
            textvariable=self.bar_var,
            bg="#2c2c2c",
            fg=FG,
            buttonbackground=BTN,
            insertbackground=FG,
            relief="flat",
            font=("Segoe UI", 10),
        ).pack(side="left")
        tk.Label(options, text="px", bg=BG, fg=FG, font=("Segoe UI", 10)).pack(side="left", padx=(4, 16))
        tk.Checkbutton(
            options,
            text="Нейросеть, если кадр крупнее пикселей",
            variable=self.upscale_var,
            bg=BG,
            fg=FG,
            selectcolor="#333333",
            activebackground=BG,
            activeforeground=FG,
            font=("Segoe UI", 10),
        ).pack(side="left")
        self.model_btn = self._button(options, "Скачать Real-ESRGAN (43 МБ)", self.download_model)
        self.model_btn.pack(side="left", padx=(12, 0))

        self.canvas = tk.Canvas(self, bg=CANVAS, highlightthickness=0, height=640)
        self.canvas.pack(fill="both", expand=True, padx=12, pady=8)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Double-Button-1>", lambda _event: self.fit())
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Configure>", self._on_configure)

        zoom = tk.Frame(self, bg=BG)
        zoom.pack(fill="x", padx=12)
        tk.Label(zoom, text="Масштаб", bg=BG, fg=FG, font=("Segoe UI", 10)).pack(side="left")
        self.slider = tk.Scale(
            zoom,
            from_=1,
            to=2,
            resolution=0.001,
            orient="horizontal",
            showvalue=False,
            command=self._on_slider,
            length=420,
            bg=BG,
            fg=FG,
            troughcolor="#3a3a3a",
            highlightthickness=0,
            bd=0,
        )
        self.slider.pack(side="left", padx=8)
        self.zoom_label = tk.Label(zoom, text="", bg=BG, fg=FG, font=("Segoe UI", 10), width=8, anchor="w")
        self.zoom_label.pack(side="left")
        self._button(zoom, "Вписать", self.fit).pack(side="right")

        tk.Label(
            self,
            text="Тяните картинку · колёсико — масштаб · двойной щелчок — вписать · серая черта только на экране",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).pack(fill="x", padx=12, pady=(4, 0))
        tk.Label(self, textvariable=self.status, bg=BG, fg=FG, font=("Segoe UI", 10), anchor="w").pack(
            fill="x", padx=12, pady=(2, 4)
        )
        self.save_btn = self._button(self, "Сохранить", self.save)
        self.save_btn.configure(state="disabled")
        self.save_btn.pack(fill="x", padx=12, pady=(0, 12))

    def _button(self, parent: tk.Widget, text: str, command) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=BTN,
            fg=FG,
            activebackground="#4a4a4a",
            activeforeground=FG,
            relief="flat",
            padx=10,
            pady=4,
            font=("Segoe UI", 10),
        )

    def choose_file(self) -> None:
        if self._busy:
            return
        selected = filedialog.askopenfilename(
            parent=self,
            filetypes=[
                ("Картинки", "*.jpg *.jpeg *.png *.webp *.tif *.tiff *.bmp"),
                ("Все файлы", "*.*"),
            ],
        )
        if selected:
            self.load_image(Path(selected))

    def load_image(self, path: Path) -> None:
        try:
            with Image.open(path) as incoming:
                transposed = ImageOps.exif_transpose(incoming) or incoming
                transposed.load()
                image = transposed.copy()
        except Exception as exc:
            messagebox.showerror("Normal Black Row", f"Не удалось открыть файл:\n{exc}", parent=self)
            return
        self.image = image
        self.source_path = path
        self.preview, self.preview_ratio = _preview_source(image)
        self.cx = image.width / 2
        self.cy = image.height / 2
        _, _, content_w, content_h = nbr.content_box(*self.preset, self.side, self.bar)
        self.scale = nbr.minimum_scale(image.width, image.height, content_w, content_h)
        self.title(f"Normal Black Row — {path.name}")
        self.save_btn.configure(state="normal")
        self._reclamp()
        self.request_redraw(sharp=True)

    def choose_preset(self, width: int, height: int) -> None:
        self.custom = False
        self.preset = (width, height)
        self._style_presets()
        self._reclamp()
        self.request_redraw(sharp=False)
        self._arm_sharp()

    def _apply_custom(self, *_args) -> None:
        if self._syncing:
            return
        try:
            width = int(self.custom_width_var.get())
        except (tk.TclError, ValueError):
            return
        if not nbr.CUSTOM_WIDTH_MIN <= width <= nbr.CUSTOM_WIDTH_MAX:
            return
        try:
            nbr.content_box(width, nbr.FRAME_HEIGHT, self.side, self.bar)
        except ValueError as exc:
            self.status.set(str(exc))
            return
        if self.custom and self.preset == (width, nbr.FRAME_HEIGHT):
            return
        self.custom = True
        self.preset = (width, nbr.FRAME_HEIGHT)
        self._style_presets()
        self._reclamp()
        self.request_redraw(sharp=False)
        self._arm_sharp()

    def fit(self) -> None:
        if self.image is None:
            return
        self.cx = self.image.width / 2
        self.cy = self.image.height / 2
        _, _, content_w, content_h = nbr.content_box(*self.preset, self.side, self.bar)
        self.scale = nbr.minimum_scale(self.image.width, self.image.height, content_w, content_h)
        self._reclamp()
        self.request_redraw(sharp=True)

    def _style_presets(self) -> None:
        for preset, button in self.preset_buttons.items():
            selected = (not self.custom) and preset == self.preset
            if selected:
                button.configure(bg="#f2f2f2", fg="#161616", activebackground="#ffffff", activeforeground="#161616")
            else:
                button.configure(bg=BTN, fg=FG, activebackground="#4a4a4a", activeforeground=FG)
        if self.custom:
            self.custom_btn.configure(bg="#f2f2f2", fg="#161616", activebackground="#ffffff", activeforeground="#161616")
            self.custom_width.configure(bg="#f2f2f2", fg="#161616")
        else:
            self.custom_btn.configure(bg=BTN, fg=FG, activebackground="#4a4a4a", activeforeground=FG)
            self.custom_width.configure(bg="#2c2c2c", fg=FG)

    def _on_side(self, label: str) -> None:
        self.side = SIDE_BY_LABEL[label]
        self._reclamp()
        self.request_redraw(sharp=False)
        self._arm_sharp()

    def _on_bar(self, *_args) -> None:
        if self._syncing:
            return
        try:
            value = int(self.bar_var.get())
        except (tk.TclError, ValueError):
            return
        if value < 0:
            return
        try:
            nbr.content_box(self.preset[0], self.preset[1], self.side, value)
        except ValueError as exc:
            self.status.set(str(exc))
            return
        self.bar = value
        self._reclamp()
        self.request_redraw(sharp=False)
        self._arm_sharp()

    def _bounds(self) -> tuple[float, float]:
        _, _, content_w, content_h = nbr.content_box(*self.preset, self.side, self.bar)
        low = nbr.minimum_scale(self.image.width, self.image.height, content_w, content_h)
        high = nbr.maximum_scale(content_w, content_h, low)
        if high <= low:
            high = low + 0.01
        return low, high

    def _reclamp(self) -> None:
        if self.image is None:
            return
        low, high = self._bounds()
        self.scale = min(max(self.scale, low), high)
        _, _, content_w, content_h = nbr.content_box(*self.preset, self.side, self.bar)
        _x, _y, _w, _h, self.cx, self.cy, self.scale = nbr.framed_crop(
            self.image.width, self.image.height, content_w, content_h, self.scale, self.cx, self.cy
        )
        self._sync_slider()

    def _sync_slider(self) -> None:
        if self.image is None:
            return
        low, high = self._bounds()
        self._syncing = True
        try:
            self.slider.configure(from_=low, to=high)
            self.slider.set(self.scale)
        finally:
            self._syncing = False
        self.zoom_label.configure(text=f"{self.scale * 100:.0f}%")

    def _on_slider(self, value: str) -> None:
        if self._syncing or self.image is None:
            return
        self.scale = float(value)
        self.request_redraw(sharp=False)
        self._arm_sharp()

    def request_redraw(self, sharp: bool = False) -> None:
        self._want_sharp = sharp
        if self._redraw_job is None:
            self._redraw_job = self.after_idle(self._redraw)

    def _arm_sharp(self) -> None:
        if self._sharp_job is not None:
            self.after_cancel(self._sharp_job)
        self._sharp_job = self.after(180, self._redraw_sharp)

    def _redraw_sharp(self) -> None:
        self._sharp_job = None
        self.request_redraw(sharp=True)

    def _on_configure(self, _event) -> None:
        self.request_redraw(sharp=False)

    def _redraw(self) -> None:
        self._redraw_job = None
        self.canvas.delete("all")
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        if width < 80 or height < 80:
            return
        if self.image is None:
            self.canvas.create_text(
                width / 2,
                height / 2,
                text="Откройте картинку",
                fill="#d7d7d7",
                font=("Segoe UI", 16),
            )
            return

        target_w, target_h = self.preset
        origin_x, origin_y, content_w, content_h = nbr.content_box(target_w, target_h, self.side, self.bar)
        pad = 28
        fit = min((width - pad) / target_w, (height - pad) / target_h)
        frame_w = target_w * fit
        frame_h = target_h * fit
        frame_x = (width - frame_w) / 2
        frame_y = (height - frame_h) / 2
        photo_x = frame_x + origin_x * fit
        photo_y = frame_y + origin_y * fit
        photo_w = max(1.0, content_w * fit)
        photo_h = max(1.0, content_h * fit)
        self.photo_screen = (photo_x, photo_y, photo_w, photo_h)

        x, y, crop_w, crop_h, self.cx, self.cy, self.scale = nbr.framed_crop(
            self.image.width, self.image.height, content_w, content_h, self.scale, self.cx, self.cy
        )
        if self._want_sharp or self.preview is None:
            source = self.image
            box = (x, y, crop_w, crop_h)
            resample = Image.Resampling.LANCZOS
        else:
            source = self.preview
            ratio = self.preview_ratio
            box = (x * ratio, y * ratio, crop_w * ratio, crop_h * ratio)
            resample = Image.Resampling.BILINEAR

        shot = nbr.sample(source, box, max(1, math.ceil(photo_w)), max(1, math.ceil(photo_h)), resample)
        if shot.mode not in {"RGB", "RGBA"}:
            shot = shot.convert("RGB")
        self._photo = ImageTk.PhotoImage(shot)
        self.canvas.create_rectangle(
            frame_x, frame_y, frame_x + frame_w, frame_y + frame_h, fill="#000000", outline="#9a9a9a"
        )
        self.canvas.create_image(photo_x, photo_y, image=self._photo, anchor="nw")
        self._draw_guide(frame_x, frame_y, frame_w, frame_h, photo_x, photo_y, photo_w, photo_h)
        self._sync_slider()
        self._write_status(content_w, content_h)

    def _draw_guide(
        self,
        frame_x: float,
        frame_y: float,
        frame_w: float,
        frame_h: float,
        photo_x: float,
        photo_y: float,
        photo_w: float,
        photo_h: float,
    ) -> None:
        if self.bar <= 0:
            return
        if self.side == "left":
            points = (photo_x, frame_y, photo_x, frame_y + frame_h)
        elif self.side == "right":
            edge = photo_x + photo_w
            points = (edge, frame_y, edge, frame_y + frame_h)
        elif self.side == "top":
            points = (frame_x, photo_y, frame_x + frame_w, photo_y)
        else:
            edge = photo_y + photo_h
            points = (frame_x, edge, frame_x + frame_w, edge)
        self.canvas.create_line(*points, fill="#8d8d8d")

    def _write_status(self, content_w: int, content_h: int) -> None:
        target_w, target_h = self.preset
        source = f"{self.image.width}×{self.image.height}"
        if self.scale > 1.01:
            scale_text = f"нужно увеличение ×{self.scale:.2f}"
        elif self.scale < 0.99:
            scale_text = "картинка больше кадра, будет обрезка"
        else:
            scale_text = "масштаб около 1:1"
        self.status.set(
            f"Исходник {source} · кадр {target_w}×{target_h} · "
            f"фото {content_w}×{content_h} · {scale_text}"
        )

    def _on_press(self, event) -> None:
        if self.image is None:
            return
        self._drag = (event.x, event.y, self.cx, self.cy)

    def _on_drag(self, event) -> None:
        if self._drag is None or self.image is None or self.photo_screen is None:
            return
        start_x, start_y, cx0, cy0 = self._drag
        _px, _py, photo_w, photo_h = self.photo_screen
        _, _, content_w, content_h = nbr.content_box(*self.preset, self.side, self.bar)
        self.cx = cx0 - (event.x - start_x) * (content_w / self.scale) / photo_w
        self.cy = cy0 - (event.y - start_y) * (content_h / self.scale) / photo_h
        self.request_redraw(sharp=False)

    def _on_release(self, _event) -> None:
        self._drag = None
        if self.image is not None:
            self.request_redraw(sharp=True)

    def _on_wheel(self, event) -> None:
        if self.image is None or self.photo_screen is None or event.delta == 0:
            return
        factor = 1.1 if event.delta > 0 else 1 / 1.1
        photo_x, photo_y, photo_w, photo_h = self.photo_screen
        rel_x = (event.x - photo_x) / photo_w
        rel_y = (event.y - photo_y) / photo_h
        if not (0 <= rel_x <= 1 and 0 <= rel_y <= 1):
            rel_x = 0.5
            rel_y = 0.5
        _, _, content_w, content_h = nbr.content_box(*self.preset, self.side, self.bar)
        x, y, crop_w, crop_h, *_rest = nbr.framed_crop(
            self.image.width, self.image.height, content_w, content_h, self.scale, self.cx, self.cy
        )
        point_x = x + rel_x * crop_w
        point_y = y + rel_y * crop_h
        low, high = self._bounds()
        new_scale = min(max(self.scale * factor, low), high)
        new_w = content_w / new_scale
        new_h = content_h / new_scale
        self.cx = point_x - rel_x * new_w + new_w / 2
        self.cy = point_y - rel_y * new_h + new_h / 2
        self.scale = new_scale
        self.request_redraw(sharp=False)
        self._arm_sharp()

    def _nudge(self, event, dx: int, dy: int):
        focused = self.focus_get()
        if isinstance(focused, (tk.Spinbox, tk.Entry, tk.Scale)):
            return None
        if self.image is None:
            return "break"
        _, _, content_w, content_h = nbr.content_box(*self.preset, self.side, self.bar)
        self.cx += (content_w / self.scale) * 0.02 * dx
        self.cy += (content_h / self.scale) * 0.02 * dy
        self.request_redraw(sharp=False)
        self._arm_sharp()
        return "break"

    def _check_update_async(self) -> None:
        def work() -> None:
            remote = nbr.update_available()
            if remote:
                self.after(0, lambda: self._offer_update(remote))

        threading.Thread(target=work, daemon=True).start()

    def _update_progress(self, done: int, total: int) -> None:
        if total:
            self.status.set(f"Скачиваю обновление: {done / 1048576:.0f} из {total / 1048576:.0f} МБ")
        else:
            self.status.set(f"Скачиваю обновление: {done / 1048576:.0f} МБ")

    def _offer_update(self, remote: str) -> None:
        if self._busy:
            return
        local = ".".join(str(part) for part in nbr.local_version())
        agreed = messagebox.askyesno(
            "Обновление",
            f"Есть версия {remote}. Сейчас установлена {local}.\n\nОбновить?",
            parent=self,
        )
        if not agreed:
            return
        self._busy = True
        self.status.set("Обновляю…")

        def work() -> None:
            try:
                nbr.apply_update(
                    lambda done, total: self.after(
                        0, lambda done=done, total=total: self._update_progress(done, total)
                    )
                )
            except Exception as exc:
                self.after(0, lambda: self._update_failed(exc))
                return
            self.after(0, self._restart_after_update)

        threading.Thread(target=work, daemon=True).start()

    def _update_failed(self, exc: Exception) -> None:
        self._busy = False
        messagebox.showerror("Обновление", f"Не удалось обновить:\n{exc}", parent=self)
        self.status.set("Обновление не установилось")

    def _restart_after_update(self) -> None:
        messagebox.showinfo("Обновление", "Обновление установлено. Программа перезапустится.", parent=self)
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]], cwd=nbr.app_dir())
        self.destroy()

    def _refresh_model_button(self) -> None:
        if nbr.find_realesrgan() is not None:
            self.model_btn.configure(text="Real-ESRGAN готов", state="disabled")
        else:
            self.model_btn.configure(text="Скачать Real-ESRGAN (43 МБ)", state="normal")

    def _download_progress(self, done: int, total: int) -> None:
        if total:
            self.status.set(f"Скачиваю Real-ESRGAN: {done / 1048576:.0f} из {total / 1048576:.0f} МБ")
        else:
            self.status.set(f"Скачиваю Real-ESRGAN: {done / 1048576:.0f} МБ")

    def download_model(self, then=None) -> None:
        if self._busy:
            return
        self._busy = True
        self.model_btn.configure(state="disabled")

        def work() -> None:
            try:
                nbr.download_realesrgan(
                    lambda done, total: self.after(
                        0, lambda done=done, total=total: self._download_progress(done, total)
                    )
                )
            except Exception as exc:
                self.after(0, lambda: self._download_failed(exc))
                return
            self.after(0, lambda: self._download_finished(then))

        threading.Thread(target=work, daemon=True).start()

    def _download_failed(self, exc: Exception) -> None:
        self._busy = False
        self._refresh_model_button()
        messagebox.showerror("Normal Black Row", f"Не удалось скачать Real-ESRGAN:\n{exc}", parent=self)

    def _download_finished(self, then) -> None:
        self._busy = False
        self._refresh_model_button()
        self.status.set("Real-ESRGAN готов")
        if then is not None:
            then()

    def save(self) -> None:
        if self._busy or self.image is None or self.source_path is None:
            return
        target_w, target_h = self.preset
        suffix = self.source_path.suffix.lower()
        if suffix not in nbr.FORMAT_BY_SUFFIX:
            suffix = ".jpg"
        selected = filedialog.asksaveasfilename(
            parent=self,
            initialdir=self.source_path.parent,
            initialfile=f"{self.source_path.stem}_{target_w}x{target_h}{suffix}",
            defaultextension=suffix,
            filetypes=[("JPEG", "*.jpg"), ("PNG", "*.png"), ("WebP", "*.webp")],
        )
        if not selected:
            return
        destination = Path(selected)
        need_upscale = self.scale > 1.01 and bool(self.upscale_var.get())
        if need_upscale and nbr.find_realesrgan() is None:
            answer = messagebox.askyesnocancel(
                "Real-ESRGAN",
                "Кадр крупнее исходных пикселей.\n\n"
                "Да — скачать Real-ESRGAN (43 МБ) и увеличить нейросетью.\n"
                "Нет — сохранить обычным увеличением.\n"
                "Отмена — не сохранять.",
                parent=self,
            )
            if answer is None:
                return
            if answer:
                self.download_model(then=lambda: self._start_export(destination, neural=True))
                return
            need_upscale = False
        self._start_export(destination, neural=need_upscale)

    def _start_export(self, destination: Path, neural: bool) -> None:
        if self.image is None:
            return
        snapshot = (self.image.copy(), self.preset, self.side, self.bar, self.scale, self.cx, self.cy)
        self._busy = True
        self.save_btn.configure(state="disabled")
        self.status.set("Увеличиваю Real-ESRGAN…" if neural else "Сохраняю…")

        def work() -> None:
            try:
                result = self._render_snapshot(snapshot, neural)
                nbr.save_image(result, destination, None)
            except Exception as exc:
                self.after(0, lambda: self._export_failed(exc, destination, neural))
                return
            self.after(0, lambda: self._export_done(destination))

        threading.Thread(target=work, daemon=True).start()

    def _render_snapshot(self, snapshot, neural: bool) -> Image.Image:
        image, preset, side, bar, scale, cx, cy = snapshot
        target_w, target_h = preset
        if neural:
            _ox, _oy, content_w, content_h = nbr.content_box(target_w, target_h, side, bar)
            x, y, crop_w, crop_h, *_rest = nbr.framed_crop(
                image.width, image.height, content_w, content_h, scale, cx, cy
            )
            exe = nbr.find_realesrgan()
            if exe is None:
                raise FileNotFoundError("Real-ESRGAN не найден")
            photo = nbr.upscale_crop(image, (x, y, crop_w, crop_h), content_w, content_h, exe)
            return nbr.compose(photo, target_w, target_h, side, bar)
        return nbr.render_framed(image, target_w, target_h, side, bar, scale, cx, cy)

    def _export_failed(self, exc: Exception, destination: Path, neural: bool) -> None:
        self._busy = False
        self.save_btn.configure(state="normal")
        if neural:
            retry = messagebox.askyesno(
                "Normal Black Row",
                f"Real-ESRGAN не сработал:\n{exc}\n\nСохранить обычным увеличением?",
                parent=self,
            )
            if retry:
                self._start_export(destination, neural=False)
                return
        else:
            messagebox.showerror("Normal Black Row", f"Не удалось сохранить:\n{exc}", parent=self)
        self.status.set("Сохранение отменено")

    def _export_done(self, destination: Path) -> None:
        self._busy = False
        self.save_btn.configure(state="normal")
        target_w, target_h = self.preset
        self.status.set(f"Сохранено {destination.name} · {target_w}×{target_h}")


def main() -> None:
    _dpi()
    app = CropApp()
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
        if path.is_file():
            app.after(50, lambda: app.load_image(path))
        else:
            app.status.set(f"Файл не найден: {path}")
    app.mainloop()


if __name__ == "__main__":
    main()
