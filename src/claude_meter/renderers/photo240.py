"""240x240 JPEG for the GeeKmagic clock's Photo-mode full-screen slot."""
from __future__ import annotations

import io

from PIL import Image, ImageDraw

from claude_meter.providers import ServiceCard
from claude_meter.renderers import (
    COLOR_BG, COLOR_DIM, COLOR_TEXT, COLOR_TRACK, bar_color, load_font,
)

DISPLAY_SIZE = (240, 240)


class Photo240Renderer:
    def render(self, card: ServiceCard) -> bytes:
        img  = Image.new("RGB", DISPLAY_SIZE, COLOR_BG)
        draw = ImageDraw.Draw(img)

        font_title = load_font(20)
        font_pct   = load_font(34)
        font_small = load_font(14)

        draw.text((12, 8), card.title, font=font_title, fill=COLOR_TEXT)

        def draw_section(y: int, label: str, pct: float, note: str):
            pct_clamped = max(0.0, min(pct, 999.0))
            bar_pct     = min(pct_clamped, 100.0)
            color       = bar_color(pct_clamped)

            draw.text((12, y), label, font=font_small, fill=COLOR_DIM)
            pct_text = f"{pct_clamped:.0f}%"
            draw.text((216 - int(font_pct.getlength(pct_text)), y - 4),
                      pct_text, font=font_pct, fill=color)

            bar_x, bar_y, bar_w, bar_h = 12, y + 38, 216, 14
            draw.rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], fill=COLOR_TRACK)
            filled = int(bar_w * bar_pct / 100)
            if filled > 0:
                draw.rectangle([bar_x, bar_y, bar_x + filled, bar_y + bar_h], fill=color)

            draw.text((12, bar_y + bar_h + 4), note, font=font_small, fill=COLOR_DIM)

        draw_section(40,  card.row1_label, card.row1_pct, card.row1_note)
        draw_section(140, card.row2_label, card.row2_pct, card.row2_note)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        return buf.getvalue()
