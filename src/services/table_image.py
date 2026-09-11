"""Render a small data table to a PNG that looks like a spreadsheet grid.

WhatsApp has no table markup and its monospace block wraps/misaligns on many
phones, so anything tabular for operators goes out as an image. Pure PIL, no
browser. Fonts: DejaVu (VPS) → Arial/Consolas (Windows dev) → PIL default.
"""
from __future__ import annotations

import io
import os
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
]
_BOLD_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]

# Excel-ish palette
_HEADER_BG = (31, 78, 121)      # dark blue
_HEADER_FG = (255, 255, 255)
_ROW_ALT   = (242, 246, 250)
_ROW_BG    = (255, 255, 255)
_GRID      = (191, 191, 191)
_TEXT      = (33, 33, 33)
_TOTAL_BG  = (221, 235, 247)
_TITLE_FG  = (31, 78, 121)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for p in (_BOLD_CANDIDATES if bold else _FONT_CANDIDATES):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


@dataclass
class Table:
    headers: list[str]
    rows: list[list[str]]
    align: str = ""                       # one char per column: 'l' or 'r'; default left
    footer: list[str] | None = None       # rendered as a highlighted total row
    title: str | None = None


@dataclass
class Sheet:
    """One image, one or more tables stacked vertically."""
    title: str
    tables: list[Table] = field(default_factory=list)
    subtitle: str | None = None


def render_png(sheet: Sheet, scale: int = 2) -> bytes:
    """Returns PNG bytes. `scale` renders at 2x for crisp zoom on phones."""
    fs = 15 * scale
    f, fb, ft = _font(fs), _font(fs, bold=True), _font(int(fs * 1.25), bold=True)
    pad_x, pad_y = 12 * scale, 8 * scale
    margin = 20 * scale
    row_h = fs + 2 * pad_y

    def text_w(s: str, font) -> int:
        return int(font.getlength(s))

    # Measure every table
    measured = []
    for t in sheet.tables:
        ncol = len(t.headers)
        widths = [text_w(h, fb) for h in t.headers]
        for r in [*t.rows, *([t.footer] if t.footer else [])]:
            for i in range(ncol):
                widths[i] = max(widths[i], text_w(str(r[i]) if i < len(r) else "", fb))
        widths = [w + 2 * pad_x for w in widths]
        measured.append(widths)

    table_w = max(sum(w) for w in measured) if measured else 0
    title_w = max(text_w(sheet.title, ft), text_w(sheet.subtitle or "", f))
    W = max(table_w, title_w) + 2 * margin

    H = margin + int(fs * 1.25) + pad_y
    if sheet.subtitle:
        H += fs + pad_y
    for t in sheet.tables:
        if t.title:
            H += fs + pad_y * 2
        H += row_h * (1 + len(t.rows) + (1 if t.footer else 0)) + margin

    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)

    y = margin
    d.text((margin, y), sheet.title, font=ft, fill=_TITLE_FG)
    y += int(fs * 1.25) + pad_y
    if sheet.subtitle:
        d.text((margin, y), sheet.subtitle, font=f, fill=(90, 90, 90))
        y += fs + pad_y

    for t, widths in zip(sheet.tables, measured):
        if t.title:
            y += pad_y
            d.text((margin, y), t.title, font=fb, fill=_TEXT)
            y += fs + pad_y
        # stretch this table to the widest one so stacked tables line up on the right edge
        extra = table_w - sum(widths)
        if extra > 0:
            widths = widths[:]
            widths[0] += extra
        x0 = margin
        align = (t.align + "l" * len(t.headers))[: len(t.headers)]

        def draw_row(cells, bg, font, fg, yy):
            x = x0
            d.rectangle([x, yy, x + sum(widths), yy + row_h], fill=bg)
            for i, w in enumerate(widths):
                s = str(cells[i]) if i < len(cells) else ""
                tw = text_w(s, font)
                tx = x + (w - pad_x - tw) if align[i] == "r" else x + pad_x
                d.text((tx, yy + pad_y), s, font=font, fill=fg)
                d.line([x, yy, x, yy + row_h], fill=_GRID, width=scale)
                x += w
            d.line([x, yy, x, yy + row_h], fill=_GRID, width=scale)
            d.line([x0, yy + row_h, x, yy + row_h], fill=_GRID, width=scale)

        d.line([x0, y, x0 + sum(widths), y], fill=_GRID, width=scale)
        draw_row(t.headers, _HEADER_BG, fb, _HEADER_FG, y)
        y += row_h
        for i, r in enumerate(t.rows):
            draw_row(r, _ROW_ALT if i % 2 else _ROW_BG, f, _TEXT, y)
            y += row_h
        if t.footer:
            draw_row(t.footer, _TOTAL_BG, fb, _TEXT, y)
            y += row_h
        y += margin

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
