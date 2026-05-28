"""Fix overlapping icon in poster1.png — replace with correct icon from logo file."""
from PIL import Image
import numpy as np

LOGO_PATH = r"D:\Work\Claude Projects\AI Watsapp PG Accountant\Coveezo Banner (3 x 4 in) (12 x 18 in) Logo.png"
POSTER_PATH = r"D:\Work\Claude Projects\AI Watsapp PG Accountant\poster1.png"
OUT_PATH = r"D:\Work\Claude Projects\AI Watsapp PG Accountant\poster1_fixed.png"

logo = Image.open(LOGO_PATH).convert("RGBA")
poster = Image.open(POSTER_PATH).convert("RGBA")

la = np.array(logo)
pa = np.array(poster)

# ── Locate COZEEVO wordmark in logo file ───────────────────────────────────────
# Logo content: y=95-220 (pink COZEEVO text), full wordmark width x=65-780
logo_wm = logo.crop((65, 95, 780, 222))  # width=715, height=127

# ── Locate wordmark area in poster ────────────────────────────────────────────
# From analysis: pink COZEEVO text in poster spans y≈20-105, horizontally centered
# Find leftmost/rightmost pink pixel cols (inner 80% of width) at key row y=70
poster_w, poster_h = poster.size
inner_l, inner_r = int(poster_w * 0.10), int(poster_w * 0.90)

row70 = pa[70, inner_l:inner_r, :]
r70, g70, b70 = row70[:, 0], row70[:, 1], row70[:, 2]
pink_mask = (r70.astype(int) > 180) & (g70.astype(int) < 80) & (b70.astype(int) > 80)
pink_cols = np.where(pink_mask)[0]

if len(pink_cols) < 2:
    raise RuntimeError("Could not locate COZEEVO text in poster at y=70")

text_left = pink_cols[0] + inner_l
text_right = pink_cols[-1] + inner_l
text_width = text_right - text_left
print(f"Poster wordmark x: {text_left} - {text_right} (width {text_width})")

# Find top/bottom of wordmark in poster
center_col = (text_left + text_right) // 2
col_data = pa[:180, center_col - 20:center_col + 20, :]
r_c, g_c, b_c, a_c = col_data[:, :, 0], col_data[:, :, 1], col_data[:, :, 2], col_data[:, :, 3]
pink_rows_mask = ((r_c.astype(int) > 180) & (g_c.astype(int) < 80) & (b_c.astype(int) > 80)).any(axis=1)
# Also include icon rows (purple/cyan)
icon_rows_mask = (
    ((r_c.astype(int) < 140) & (g_c.astype(int) < 80) & (b_c.astype(int) > 100)) |
    ((r_c.astype(int) < 50) & (g_c.astype(int) > 140) & (b_c.astype(int) > 200))
).any(axis=1)
active_rows = np.where(pink_rows_mask | icon_rows_mask)[0]
text_top = max(0, active_rows[0] - 6) if len(active_rows) else 20
text_bottom = active_rows[-1] + 6 if len(active_rows) else 100
text_height = text_bottom - text_top
print(f"Poster wordmark y: {text_top} - {text_bottom} (height {text_height})")

# ── Scale logo wordmark to fit poster area ────────────────────────────────────
# Keep same horizontal extent, scale height proportionally
scale = text_width / logo_wm.width
new_h = max(int(logo_wm.height * scale), text_height)
logo_scaled = logo_wm.resize((text_width, new_h), Image.LANCZOS)

# ── Paste into poster ─────────────────────────────────────────────────────────
# Create a white patch to erase old wordmark first (10px padding each side)
erase_top = max(0, text_top - 5)
erase_bottom = min(poster_h, text_top + new_h + 5)
erase_left = max(0, text_left - 5)
erase_right = min(poster_w, text_right + 5)

poster_out = poster.copy()
white_patch = Image.new("RGBA", (erase_right - erase_left, erase_bottom - erase_top), (255, 255, 255, 255))
poster_out.paste(white_patch, (erase_left, erase_top))

# Paste scaled logo wordmark (white background → use it directly)
paste_x = text_left
paste_y = text_top
poster_out.paste(logo_scaled, (paste_x, paste_y), logo_scaled)

poster_out.convert("RGB").save(OUT_PATH, "PNG", optimize=False)
print(f"Saved: {OUT_PATH}")
