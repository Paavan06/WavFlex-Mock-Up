"""
Product Tagging screen (UI MOCK) — standalone, separate from the WavFlex app.

Mock of the planned product/brand tagging feature: for an image, or for each
sampled timestamp of a video, show which products/brands appear in the frame
(e.g. "ZUS Coffee cup on the table at 00:42").

NOTHING here calls an AI model. Detections are generated deterministically from
the file name so the same file always shows the same mock results. Real frames
are extracted with FFmpeg for the preview so the flow feels realistic, but the
bounding boxes and labels are fake.
"""

import csv
import os
import random
import re
import subprocess
import sys
import tempfile
import threading
import time
from typing import Dict, List, Optional

import flet as ft

# --- Settings & theme (copied from WavFlex so this app stands alone) ---
APP_DIR = os.path.dirname(os.path.abspath(__file__))
EXPORT_DIR = os.path.join(APP_DIR, "exports")
FFMPEG_BIN = "ffmpeg"
FFPROBE_BIN = "ffprobe"

CHARCOAL = "#1F2933"
CHARCOAL_SOFT = "#374151"
CARD_BG = "#FFFFFF"
BORDER_COLOR = "#D6D2CB"
SUCCESS_GREEN = "#2E7D32"
WARNING_YELLOW = "#C77800"
INFO_PURPLE = "#6D4DD6"

_NO_WINDOW = (
    {"creationflags": subprocess.CREATE_NO_WINDOW}
    if sys.platform.startswith("win")
    else {}
)


def get_duration_seconds(path: str) -> float:
    """Video duration via ffprobe, falling back to parsing FFmpeg's header
    (some files, e.g. Windows screen recordings, have no duration field)."""
    try:
        out = subprocess.run(
            [FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=30, **_NO_WINDOW,
        ).stdout.strip()
        if out and out != "N/A":
            return float(out)
    except Exception:
        pass
    try:
        err = subprocess.run(
            [FFMPEG_BIN, "-hide_banner", "-i", path],
            capture_output=True, text=True, timeout=30, **_NO_WINDOW,
        ).stderr
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
        if m:
            h, mnt, s = m.groups()
            return int(h) * 3600 + int(mnt) * 60 + float(s)
    except Exception:
        pass
    return 0.0

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".avi", ".m4v", ".wmv", ".webm", ".mxf")

# Mock product catalogue: brand -> (product seen in frame, category, colour)
MOCK_CATALOGUE: Dict[str, tuple] = {
    "ZUS Coffee": ("Iced Spanish Latte cup", "Beverage", "#1E3A8A"),
    "Tealive": ("Brown Sugar Pearl Milk Tea", "Beverage", "#7C3AED"),
    "Starbucks": ("Takeaway coffee cup", "Beverage", "#047857"),
    "Milo": ("Milo tin", "Beverage", "#15803D"),
    "100Plus": ("Isotonic drink can", "Beverage", "#2563EB"),
    "Gardenia": ("Bread loaf packaging", "Food", "#D97706"),
    "Maggi": ("Instant noodle pack", "Food", "#DC2626"),
    "Petronas": ("Petrol station signage", "Signage", "#0D9488"),
    "Grab": ("Rider jacket & helmet", "Apparel", "#16A34A"),
    "Samsung": ("Smartphone (logo visible)", "Electronics", "#1D4ED8"),
}

STATUS_COLORS = {
    "Pending": WARNING_YELLOW,
    "Confirmed": SUCCESS_GREEN,
    "Rejected": "#9CA3AF",
}

PREVIEW_W, PREVIEW_H = 480, 270
TIMELINE_W = 560


def _fmt_t(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60:02d}:{s % 60:02d}"


class ProductTaggingView:
    """Product Tagging (mock) screen."""

    def __init__(self, page: ft.Page):
        self.page: ft.Page = page

        # State (survives tab switches)
        self.file_path: Optional[str] = None
        self.media_type: Optional[str] = None  # "Video" | "Image" | "Demo"
        self.duration: float = 0.0
        self.interval: int = 2
        self.min_conf: float = 0.5
        self.brand_filter: str = "All brands"
        self.detections: List[Dict] = []
        self.selected_idx: Optional[int] = None
        self.analyzing = False
        self._frame_dir = tempfile.mkdtemp(prefix="wavflex_ptag_")

        self.file_picker = ft.FilePicker(on_result=self._on_file_picked)
        self.page.overlay.append(self.file_picker)

    # ------------------------------------------------------------------ build

    def build(self) -> ft.Control:
        self.file_label = ft.Text(
            self._file_label_text(), size=13, color=CHARCOAL_SOFT, selectable=True
        )
        self.progress_bar = ft.ProgressBar(value=0, visible=False, width=320)
        self.progress_text = ft.Text("", size=12, color=CHARCOAL_SOFT)
        self.analyze_btn = ft.ElevatedButton(
            "Analyze products",
            icon=ft.Icons.MANAGE_SEARCH,
            on_click=self._on_analyze,
            disabled=self.media_type is None or self.analyzing,
            style=ft.ButtonStyle(bgcolor=CHARCOAL, color=ft.Colors.WHITE),
        )
        self.results_area = ft.Column(spacing=16)

        mock_banner = ft.Container(
            bgcolor=ft.Colors.with_opacity(0.12, WARNING_YELLOW),
            border=ft.border.all(1, WARNING_YELLOW),
            border_radius=8,
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.SCIENCE_OUTLINED, color=WARNING_YELLOW, size=18),
                    ft.Text(
                        "MOCK — detections below are fake sample data. "
                        "No AI model is called.",
                        size=12,
                        color=CHARCOAL,
                    ),
                ],
                spacing=8,
            ),
        )

        setup_card = self._card(
            ft.Column(
                [
                    ft.Text("1. Choose media", size=15, weight=ft.FontWeight.BOLD),
                    ft.Row(
                        [
                            ft.OutlinedButton(
                                "Select video or image",
                                icon=ft.Icons.UPLOAD_FILE,
                                on_click=self._pick_file,
                            ),
                            ft.TextButton(
                                "Use demo video (no file)",
                                icon=ft.Icons.MOVIE_FILTER_OUTLINED,
                                on_click=self._use_demo,
                            ),
                        ],
                        wrap=True,
                    ),
                    self.file_label,
                    ft.Divider(height=8, color=BORDER_COLOR),
                    ft.Text("2. Settings", size=15, weight=ft.FontWeight.BOLD),
                    ft.Row(
                        [
                            ft.Dropdown(
                                label="Sample a frame every",
                                width=200,
                                value=str(self.interval),
                                options=[
                                    ft.dropdown.Option(str(s), f"{s} seconds")
                                    for s in (1, 2, 5, 10)
                                ],
                                on_change=self._on_interval_change,
                            ),
                            ft.Column(
                                [
                                    ft.Text(
                                        "Brands to watch (catalogue)",
                                        size=12,
                                        color=CHARCOAL_SOFT,
                                    ),
                                    ft.Row(
                                        [
                                            self._chip(b, MOCK_CATALOGUE[b][2])
                                            for b in MOCK_CATALOGUE
                                        ],
                                        wrap=True,
                                        spacing=6,
                                        run_spacing=6,
                                        width=620,
                                    ),
                                ],
                                spacing=6,
                            ),
                        ],
                        spacing=24,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                        wrap=True,
                    ),
                    ft.Divider(height=8, color=BORDER_COLOR),
                    ft.Row(
                        [
                            self.analyze_btn,
                            ft.Column(
                                [self.progress_bar, self.progress_text], spacing=4
                            ),
                        ],
                        spacing=16,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=10,
            )
        )

        self._render_results()

        return ft.Column(
            [
                ft.Row(
                    [
                        ft.Text(
                            "Product Tagging",
                            size=22,
                            weight=ft.FontWeight.BOLD,
                            color=CHARCOAL,
                        ),
                        mock_banner,
                    ],
                    spacing=16,
                    wrap=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Text(
                    "Find products and brands that appear on screen, "
                    "timestamp by timestamp.",
                    size=13,
                    color=CHARCOAL_SOFT,
                ),
                setup_card,
                self.results_area,
            ],
            spacing=14,
        )

    # -------------------------------------------------------------- handlers

    def _pick_file(self, e=None):
        self.file_picker.pick_files(
            dialog_title="Select a video or image",
            allow_multiple=False,
            allowed_extensions=[x.lstrip(".") for x in VIDEO_EXTS + IMAGE_EXTS],
        )

    def _on_file_picked(self, e: ft.FilePickerResultEvent):
        if not e.files:
            return
        path = e.files[0].path
        ext = os.path.splitext(path)[1].lower()
        self.file_path = path
        self.media_type = "Image" if ext in IMAGE_EXTS else "Video"
        self.duration = 0.0
        if self.media_type == "Video":
            try:
                self.duration = float(get_duration_seconds(path) or 0)
            except Exception:
                self.duration = 0.0
        self._reset_results()

    def _use_demo(self, e=None):
        self.file_path = None
        self.media_type = "Demo"
        self.duration = 180.0
        self._reset_results()

    def _on_interval_change(self, e):
        try:
            self.interval = int(e.control.value)
        except (TypeError, ValueError):
            self.interval = 2

    def _on_analyze(self, e=None):
        if self.analyzing or self.media_type is None:
            return
        self.analyzing = True
        self.analyze_btn.disabled = True
        self.progress_bar.visible = True
        self.progress_bar.value = 0
        self.page.update()
        threading.Thread(target=self._fake_analysis, daemon=True).start()

    def _fake_analysis(self):
        is_image = self.media_type == "Image"
        if is_image:
            steps = ["Loading image…", "Detecting objects…", "Matching brands…"]
        else:
            n_frames = max(1, int(self.duration // self.interval))
            steps = [
                f"Extracting {n_frames} frames (every {self.interval}s)…",
                "Detecting objects in each frame…",
                "Matching logos against brand catalogue…",
                "Merging detections into timeline…",
            ]
        for i, msg in enumerate(steps):
            self.progress_text.value = msg
            self.progress_bar.value = i / len(steps)
            self._safe_update()
            time.sleep(0.7)

        self.detections = self._generate_mock_detections()
        self.selected_idx = 0 if self.detections else None
        self.brand_filter = "All brands"

        self.analyzing = False
        self.analyze_btn.disabled = False
        self.progress_bar.value = 1
        self.progress_text.value = (
            f"Done — {len(self.detections)} detections (mock)"
        )
        self._render_results()
        self._safe_update()

    def _set_status(self, idx: int, status: str):
        if 0 <= idx < len(self.detections):
            self.detections[idx]["status"] = status
            self._render_results()
            self._safe_update()

    def _select(self, idx: int):
        self.selected_idx = idx
        self._render_results()
        self._safe_update()

    def _on_brand_filter(self, e):
        self.brand_filter = e.control.value or "All brands"
        self._render_results()
        self._safe_update()

    def _on_conf_change(self, e):
        self.min_conf = round(float(e.control.value), 2)
        self._render_results()
        self._safe_update()

    def _export_csv(self, e=None):
        os.makedirs(EXPORT_DIR, exist_ok=True)
        base = (
            os.path.splitext(os.path.basename(self.file_path))[0]
            if self.file_path
            else "demo"
        )
        out = os.path.join(EXPORT_DIR, f"product_tags_{base}.csv")
        try:
            with open(out, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(
                    ["Timestamp", "Brand", "Product", "Category", "Confidence",
                     "Status", "Box (x,y,w,h)"]
                )
                for d in self.detections:
                    w.writerow(
                        [_fmt_t(d["t"]), d["brand"], d["product"], d["category"],
                         f'{d["confidence"]:.2f}', d["status"],
                         ",".join(f"{v:.2f}" for v in d["box"])]
                    )
            self._toast(f"Exported (mock data): {out}", SUCCESS_GREEN)
        except PermissionError:
            self._toast(f"Can't write {out} — is it open in Excel?", "#DC2626")
        except Exception as ex:
            self._toast(f"Export failed: {ex}", "#DC2626")

    # ----------------------------------------------------------- mock engine

    def _generate_mock_detections(self) -> List[Dict]:
        seed = os.path.basename(self.file_path) if self.file_path else "demo"
        rng = random.Random(seed)
        brands = list(MOCK_CATALOGUE)
        # The example from the brief should always show up.
        picks = ["ZUS Coffee"] + rng.sample(
            [b for b in brands if b != "ZUS Coffee"], rng.randint(2, 4)
        )

        def make(brand: str, t: float, base_box, base_conf: float) -> Dict:
            product, category, _ = MOCK_CATALOGUE[brand]
            x, y, w, h = base_box
            jx, jy = rng.uniform(-0.03, 0.03), rng.uniform(-0.03, 0.03)
            return {
                "t": t,
                "brand": brand,
                "product": product,
                "category": category,
                "confidence": max(0.3, min(0.99, base_conf + rng.uniform(-0.08, 0.08))),
                "box": (
                    max(0.0, min(1 - w, x + jx)),
                    max(0.0, min(1 - h, y + jy)),
                    w,
                    h,
                ),
                "status": "Pending",
            }

        out: List[Dict] = []
        if self.media_type == "Image" or self.duration <= 0:
            for b in picks:
                w, h = rng.uniform(0.12, 0.25), rng.uniform(0.15, 0.3)
                box = (rng.uniform(0, 1 - w), rng.uniform(0, 1 - h), w, h)
                out.append(make(b, 0.0, box, rng.uniform(0.6, 0.95)))
            return out

        step = self.interval
        n_steps = max(1, int(self.duration // step))
        for b in picks:
            w, h = rng.uniform(0.1, 0.22), rng.uniform(0.12, 0.28)
            box = (rng.uniform(0.05, 0.9 - w), rng.uniform(0.2, 0.95 - h), w, h)
            base_conf = rng.uniform(0.55, 0.95)
            for _ in range(rng.randint(1, 3)):  # 1-3 on-screen segments
                start = rng.randint(0, max(0, n_steps - 1))
                length = rng.randint(2, max(2, min(8, n_steps // 4 or 2)))
                for k in range(start, min(n_steps, start + length)):
                    out.append(make(b, float(k * step), box, base_conf))

        # De-duplicate same brand at the same timestamp, then sort by time
        seen, uniq = set(), []
        for d in sorted(out, key=lambda d: (d["t"], d["brand"])):
            key = (d["t"], d["brand"])
            if key not in seen:
                seen.add(key)
                uniq.append(d)
        return uniq

    # ------------------------------------------------------------- rendering

    def _visible(self) -> List[int]:
        return [
            i
            for i, d in enumerate(self.detections)
            if d["confidence"] >= self.min_conf
            and self.brand_filter in ("All brands", d["brand"])
        ]

    def _render_results(self):
        if not hasattr(self, "results_area"):
            return
        if not self.detections:
            self.results_area.controls = []
            return

        visible = self._visible()
        if self.selected_idx not in visible:
            self.selected_idx = visible[0] if visible else None

        self.results_area.controls = [
            self._summary_row(),
            ft.Row(
                [self._preview_card(), self._brand_summary_card()],
                spacing=16,
                wrap=True,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
            *([self._timeline_card()] if self._is_timed() else []),
            self._table_card(visible),
        ]

    def _is_timed(self) -> bool:
        return self.media_type in ("Video", "Demo") and self.duration > 0

    def _summary_row(self) -> ft.Control:
        brands = {d["brand"] for d in self.detections}
        confirmed = sum(d["status"] == "Confirmed" for d in self.detections)
        frames = (
            max(1, int(self.duration // self.interval)) if self._is_timed() else 1
        )
        cards = [
            ("Frames analyzed", str(frames), ft.Icons.PHOTO_LIBRARY_OUTLINED),
            ("Detections", str(len(self.detections)), ft.Icons.CROP_FREE),
            ("Unique brands", str(len(brands)), ft.Icons.SELL_OUTLINED),
            ("Confirmed", f"{confirmed}/{len(self.detections)}", ft.Icons.TASK_ALT),
        ]
        return ft.Row(
            [
                self._card(
                    ft.Row(
                        [
                            ft.Icon(icon, color=INFO_PURPLE),
                            ft.Column(
                                [
                                    ft.Text(label, size=12, color=CHARCOAL_SOFT),
                                    ft.Text(value, size=20, weight=ft.FontWeight.BOLD),
                                ],
                                spacing=0,
                            ),
                        ],
                        spacing=12,
                    ),
                    width=210,
                )
                for label, value, icon in cards
            ],
            spacing=12,
            wrap=True,
        )

    def _preview_card(self) -> ft.Control:
        sel = (
            self.detections[self.selected_idx]
            if self.selected_idx is not None
            else None
        )
        t = sel["t"] if sel else 0.0
        frame_src = self._frame_for(t)

        if frame_src:
            bg = ft.Image(
                src=frame_src, width=PREVIEW_W, height=PREVIEW_H, fit=ft.ImageFit.FILL
            )
        else:
            bg = ft.Container(
                width=PREVIEW_W,
                height=PREVIEW_H,
                bgcolor="#2B2B2B",
                alignment=ft.alignment.center,
                content=ft.Text(
                    f"Frame @ {_fmt_t(t)}\n(demo — no real video)",
                    color="#BBBBBB",
                    text_align=ft.TextAlign.CENTER,
                ),
            )

        # All detections at this timestamp, selected one highlighted
        boxes = []
        for i, d in enumerate(self.detections):
            if d["t"] != t:
                continue
            x, y, w, h = d["box"]
            color = MOCK_CATALOGUE[d["brand"]][2]
            is_sel = i == self.selected_idx
            boxes.append(
                ft.Container(
                    left=x * PREVIEW_W,
                    top=y * PREVIEW_H,
                    width=w * PREVIEW_W,
                    height=h * PREVIEW_H,
                    border=ft.border.all(3 if is_sel else 2, color),
                    bgcolor=ft.Colors.with_opacity(0.15 if is_sel else 0.05, color),
                    on_click=lambda e, idx=i: self._select(idx),
                )
            )
            boxes.append(
                ft.Container(
                    left=x * PREVIEW_W,
                    top=max(0, y * PREVIEW_H - 20),
                    bgcolor=color,
                    padding=ft.padding.symmetric(horizontal=6, vertical=2),
                    content=ft.Text(
                        f'{d["brand"]} {d["confidence"]:.0%}',
                        size=11,
                        color=ft.Colors.WHITE,
                        weight=ft.FontWeight.BOLD,
                    ),
                )
            )

        title = (
            f"Frame @ {_fmt_t(t)}" if self._is_timed() else "Image"
        )
        detail = (
            ft.Text(
                f'{sel["brand"]} — {sel["product"]} ({sel["category"]})',
                size=13,
                weight=ft.FontWeight.W_600,
            )
            if sel
            else ft.Text("No detection selected", size=13)
        )
        return self._card(
            ft.Column(
                [
                    ft.Text(title, size=15, weight=ft.FontWeight.BOLD),
                    ft.Stack(
                        [bg, *boxes], width=PREVIEW_W, height=PREVIEW_H
                    ),
                    detail,
                    ft.Text(
                        "Boxes and labels are mock positions.",
                        size=11,
                        italic=True,
                        color=CHARCOAL_SOFT,
                    ),
                ],
                spacing=8,
            ),
            width=PREVIEW_W + 32,
        )

    def _brand_summary_card(self) -> ft.Control:
        stats: Dict[str, Dict] = {}
        for d in self.detections:
            s = stats.setdefault(
                d["brand"], {"n": 0, "first": d["t"], "conf": 0.0}
            )
            s["n"] += 1
            s["first"] = min(s["first"], d["t"])
            s["conf"] += d["confidence"]

        rows = []
        for brand, s in sorted(stats.items(), key=lambda kv: -kv[1]["n"]):
            color = MOCK_CATALOGUE[brand][2]
            screen = s["n"] * self.interval if self._is_timed() else None
            rows.append(
                ft.Container(
                    padding=ft.padding.symmetric(vertical=6),
                    border=ft.border.only(bottom=ft.BorderSide(1, BORDER_COLOR)),
                    content=ft.Row(
                        [
                            ft.Container(width=10, height=10, bgcolor=color, border_radius=5),
                            ft.Text(brand, width=110, weight=ft.FontWeight.W_600),
                            ft.Text(
                                f"{s['n']} frames"
                                + (f" · ~{screen}s on screen" if screen else ""),
                                width=170,
                                size=12,
                            ),
                            ft.Text(
                                (f"first at {_fmt_t(s['first'])} · " if screen else "")
                                + f"avg {s['conf'] / s['n']:.0%}",
                                size=12,
                                color=CHARCOAL_SOFT,
                            ),
                        ],
                        spacing=8,
                    ),
                )
            )
        return self._card(
            ft.Column(
                [
                    ft.Text("Brands found", size=15, weight=ft.FontWeight.BOLD),
                    *rows,
                    ft.Container(height=6),
                    ft.OutlinedButton(
                        "Export CSV", icon=ft.Icons.DOWNLOAD, on_click=self._export_csv
                    ),
                ],
                spacing=4,
            ),
            width=480,
        )

    def _timeline_card(self) -> ft.Control:
        dur = max(self.duration, 1.0)
        seg_w = max(3.0, self.interval / dur * TIMELINE_W)
        by_brand: Dict[str, List[int]] = {}
        for i, d in enumerate(self.detections):
            by_brand.setdefault(d["brand"], []).append(i)

        lanes = []
        for brand, idxs in by_brand.items():
            color = MOCK_CATALOGUE[brand][2]
            marks = [
                ft.Container(
                    left=self.detections[i]["t"] / dur * TIMELINE_W,
                    top=2,
                    width=seg_w,
                    height=16,
                    bgcolor=color,
                    opacity=1.0 if i == self.selected_idx else 0.75,
                    border=(
                        ft.border.all(2, CHARCOAL) if i == self.selected_idx else None
                    ),
                    tooltip=f'{brand} @ {_fmt_t(self.detections[i]["t"])}',
                    on_click=lambda e, idx=i: self._select(idx),
                )
                for i in idxs
            ]
            lanes.append(
                ft.Row(
                    [
                        ft.Text(brand, width=110, size=12),
                        ft.Container(
                            width=TIMELINE_W,
                            height=20,
                            bgcolor="#F1EFEA",
                            border_radius=4,
                            content=ft.Stack(marks, width=TIMELINE_W, height=20),
                        ),
                    ],
                    spacing=8,
                )
            )

        axis = ft.Row(
            [
                ft.Container(width=110),
                ft.Row(
                    [ft.Text(_fmt_t(dur * f), size=11, color=CHARCOAL_SOFT)
                     for f in (0, 0.25, 0.5, 0.75, 1)],
                    width=TIMELINE_W,
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
            ],
            spacing=8,
        )
        return self._card(
            ft.Column(
                [
                    ft.Text("Timeline — when each brand is on screen",
                            size=15, weight=ft.FontWeight.BOLD),
                    *lanes,
                    axis,
                    ft.Text("Click a block to jump to that frame.",
                            size=11, italic=True, color=CHARCOAL_SOFT),
                ],
                spacing=6,
            )
        )

    def _table_card(self, visible: List[int]) -> ft.Control:
        brand_opts = ["All brands"] + sorted({d["brand"] for d in self.detections})
        filters = ft.Row(
            [
                ft.Dropdown(
                    label="Brand",
                    width=200,
                    value=self.brand_filter,
                    options=[ft.dropdown.Option(b) for b in brand_opts],
                    on_change=self._on_brand_filter,
                ),
                ft.Column(
                    [
                        ft.Text(f"Min confidence: {self.min_conf:.0%}", size=12),
                        ft.Slider(
                            min=0.3, max=0.95, divisions=13, value=self.min_conf,
                            width=220, on_change_end=self._on_conf_change,
                        ),
                    ],
                    spacing=0,
                ),
                ft.Text(f"{len(visible)} of {len(self.detections)} shown",
                        size=12, color=CHARCOAL_SOFT),
            ],
            spacing=20,
            wrap=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        rows = []
        for i in visible:
            d = self.detections[i]
            rows.append(
                ft.DataRow(
                    selected=i == self.selected_idx,
                    on_select_changed=lambda e, idx=i: self._select(idx),
                    cells=[
                        ft.DataCell(ft.Text(_fmt_t(d["t"]) if self._is_timed() else "—")),
                        ft.DataCell(
                            ft.Row(
                                [
                                    ft.Container(
                                        width=10, height=10, border_radius=5,
                                        bgcolor=MOCK_CATALOGUE[d["brand"]][2],
                                    ),
                                    ft.Text(d["brand"], weight=ft.FontWeight.W_600),
                                ],
                                spacing=6,
                            )
                        ),
                        ft.DataCell(ft.Text(d["product"])),
                        ft.DataCell(ft.Text(d["category"])),
                        ft.DataCell(ft.Text(f'{d["confidence"]:.0%}')),
                        ft.DataCell(
                            ft.Text(d["status"], color=STATUS_COLORS[d["status"]],
                                    weight=ft.FontWeight.W_600)
                        ),
                        ft.DataCell(
                            ft.Row(
                                [
                                    ft.IconButton(
                                        ft.Icons.CHECK_CIRCLE_OUTLINE,
                                        icon_color=SUCCESS_GREEN,
                                        tooltip="Confirm",
                                        on_click=lambda e, idx=i: self._set_status(idx, "Confirmed"),
                                    ),
                                    ft.IconButton(
                                        ft.Icons.CANCEL_OUTLINED,
                                        icon_color="#DC2626",
                                        tooltip="Reject (wrong product)",
                                        on_click=lambda e, idx=i: self._set_status(idx, "Rejected"),
                                    ),
                                ],
                                spacing=0,
                            )
                        ),
                    ],
                )
            )

        table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text(c, weight=ft.FontWeight.BOLD))
                for c in ("Time", "Brand", "Product", "Category",
                          "Confidence", "Status", "Review")
            ],
            rows=rows,
            heading_row_height=40,
            data_row_min_height=40,
            show_checkbox_column=False,
        )
        return self._card(
            ft.Column(
                [
                    ft.Text("All detections", size=15, weight=ft.FontWeight.BOLD),
                    filters,
                    ft.Row([table], scroll=ft.ScrollMode.AUTO),
                ],
                spacing=10,
            )
        )

    # --------------------------------------------------------------- helpers

    def _frame_for(self, t: float) -> Optional[str]:
        """Real frame for the preview (images: the file; videos: FFmpeg grab)."""
        if not self.file_path:
            return None
        if self.media_type == "Image":
            return self.file_path
        out = os.path.join(self._frame_dir, f"frame_{int(t):06d}.jpg")
        if os.path.exists(out):
            return out
        cmd = [
            FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y",
            "-ss", str(t), "-i", self.file_path,
            "-frames:v", "1", "-vf", f"scale={PREVIEW_W}:-2", out,
        ]
        try:
            subprocess.run(cmd, timeout=15, check=False, **_NO_WINDOW)
        except Exception:
            return None
        return out if os.path.exists(out) else None

    def _reset_results(self):
        self.detections = []
        self.selected_idx = None
        if hasattr(self, "file_label"):
            self.file_label.value = self._file_label_text()
            self.analyze_btn.disabled = False
            self.progress_bar.visible = False
            self.progress_text.value = ""
            self._render_results()
        self._safe_update()

    def _file_label_text(self) -> str:
        if self.media_type == "Demo":
            return "Demo video · 03:00 (no file — placeholder frames)"
        if not self.file_path:
            return "No file selected"
        extra = (
            f" · {_fmt_t(self.duration)}"
            if self.media_type == "Video" and self.duration
            else ""
        )
        return f"{self.media_type}: {os.path.basename(self.file_path)}{extra}"

    def _card(self, content: ft.Control, width: Optional[int] = None) -> ft.Control:
        return ft.Container(
            content=content,
            bgcolor=CARD_BG,
            border=ft.border.all(1, BORDER_COLOR),
            border_radius=12,
            padding=16,
            width=width,
        )

    def _chip(self, label: str, color: str) -> ft.Control:
        return ft.Container(
            padding=ft.padding.symmetric(horizontal=10, vertical=4),
            border_radius=999,
            bgcolor=ft.Colors.with_opacity(0.12, color),
            border=ft.border.all(1, color),
            content=ft.Text(label, size=12, color=color, weight=ft.FontWeight.W_600),
        )

    def _toast(self, msg: str, color: str):
        try:
            self.page.open(ft.SnackBar(ft.Text(msg), bgcolor=color))
        except Exception:
            print(msg)

    def _safe_update(self):
        try:
            self.page.update()
        except Exception:
            pass
