#!/usr/bin/env python3
"""Generate the EventCalendarGenerator app icon using Pillow.

Renders a 1024x1024 calendar icon matching the app's terracotta design system.
Output: src/eventcalendar/resources/icon.png
"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def generate_icon(size: int = 1024) -> Image.Image:
    """Generate a calendar icon with terracotta accent colors."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Design system colors
    terracotta = (204, 90, 71)        # #CC5A47
    terracotta_dark = (178, 72, 55)   # darker shade for depth
    white = (255, 255, 255)
    card_border = (220, 215, 210)     # warm gray border
    text_dark = (120, 110, 105)       # warm gray for date numbers
    text_light = (170, 162, 158)      # lighter warm gray
    shadow_color = (0, 0, 0, 25)      # subtle shadow

    # Dimensions
    margin = int(size * 0.08)
    card_left = margin
    card_top = margin
    card_right = size - margin
    card_bottom = size - margin
    corner_radius = int(size * 0.08)

    # Shadow (offset slightly down-right)
    shadow_offset = int(size * 0.012)
    shadow_img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_img)
    shadow_draw.rounded_rectangle(
        [card_left + shadow_offset, card_top + shadow_offset,
         card_right + shadow_offset, card_bottom + shadow_offset],
        radius=corner_radius,
        fill=(0, 0, 0, 30),
    )
    img = Image.alpha_composite(img, shadow_img)
    draw = ImageDraw.Draw(img)

    # White card background
    draw.rounded_rectangle(
        [card_left, card_top, card_right, card_bottom],
        radius=corner_radius,
        fill=white,
        outline=card_border,
        width=int(size * 0.003),
    )

    # Terracotta header band
    header_height = int(size * 0.22)
    header_bottom = card_top + header_height

    # Draw header with rounded top corners using a mask
    header_img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    header_draw = ImageDraw.Draw(header_img)
    # Full rounded rectangle
    header_draw.rounded_rectangle(
        [card_left, card_top, card_right, card_bottom],
        radius=corner_radius,
        fill=terracotta,
    )
    # Crop to header height by overlaying white below
    header_draw.rectangle(
        [card_left, header_bottom, card_right, card_bottom],
        fill=(0, 0, 0, 0),
    )
    # We need a cleaner approach - use mask
    header_img2 = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    header_draw2 = ImageDraw.Draw(header_img2)
    header_draw2.rounded_rectangle(
        [card_left, card_top, card_right, header_bottom + corner_radius],
        radius=corner_radius,
        fill=terracotta,
    )
    # Clip the extra rounded bottom by drawing a straight rectangle over it
    header_draw2.rectangle(
        [card_left, header_bottom, card_right, header_bottom + corner_radius],
        fill=terracotta,
    )
    # Now mask out everything below header_bottom
    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rectangle([0, 0, size, header_bottom], fill=255)
    # Also need the card shape mask
    card_mask = Image.new("L", (size, size), 0)
    card_mask_draw = ImageDraw.Draw(card_mask)
    card_mask_draw.rounded_rectangle(
        [card_left, card_top, card_right, card_bottom],
        radius=corner_radius,
        fill=255,
    )
    # Combine masks
    from PIL import ImageChops
    final_mask = ImageChops.multiply(mask, card_mask)
    header_solid = Image.new("RGBA", (size, size), terracotta + (255,))
    img = Image.composite(header_solid, img, final_mask)
    draw = ImageDraw.Draw(img)

    # Subtle darker line at bottom of header
    draw.line(
        [(card_left, header_bottom), (card_right, header_bottom)],
        fill=terracotta_dark + (255,),
        width=int(size * 0.004),
    )

    # Calendar binding rings
    ring_width = int(size * 0.04)
    ring_height = int(size * 0.10)
    ring_top = card_top - int(size * 0.02)
    ring_color = (160, 155, 150)  # warm metal gray
    ring_highlight = (190, 185, 180)

    ring_positions = [
        card_left + int((card_right - card_left) * 0.30),
        card_left + int((card_right - card_left) * 0.70),
    ]

    for rx in ring_positions:
        # Ring shadow
        draw.rounded_rectangle(
            [rx - ring_width // 2 + 2, ring_top + 2,
             rx + ring_width // 2 + 2, ring_top + ring_height + 2],
            radius=ring_width // 2,
            fill=(0, 0, 0, 20),
        )
        # Ring body
        draw.rounded_rectangle(
            [rx - ring_width // 2, ring_top,
             rx + ring_width // 2, ring_top + ring_height],
            radius=ring_width // 2,
            fill=ring_color,
        )
        # Ring highlight
        draw.rounded_rectangle(
            [rx - ring_width // 4, ring_top + 2,
             rx + ring_width // 4, ring_top + ring_height - 2],
            radius=ring_width // 4,
            fill=ring_highlight,
        )

    # Month text in header
    try:
        header_font = ImageFont.truetype("/System/Library/Fonts/SFNSText.ttf",
                                         int(size * 0.07))
    except (OSError, IOError):
        try:
            header_font = ImageFont.truetype(
                "/System/Library/Fonts/Helvetica.ttc", int(size * 0.07))
        except (OSError, IOError):
            header_font = ImageFont.load_default()

    month_text = "February"
    bbox = draw.textbbox((0, 0), month_text, font=header_font)
    text_w = bbox[2] - bbox[0]
    text_x = (card_left + card_right) // 2 - text_w // 2
    text_y = card_top + int(header_height * 0.35)
    draw.text((text_x, text_y), month_text, fill=white, font=header_font)

    # 3x3 grid of date numbers
    grid_top = header_bottom + int(size * 0.06)
    grid_bottom = card_bottom - int(size * 0.06)
    grid_left = card_left + int(size * 0.08)
    grid_right = card_right - int(size * 0.08)

    cols = 3
    rows = 3
    cell_w = (grid_right - grid_left) // cols
    cell_h = (grid_bottom - grid_top) // rows

    dates = [
        [3, 4, 5],
        [10, 11, 12],
        [17, 18, 19],
    ]

    # Highlighted date: row 1, col 1 (the "11")
    highlight_row, highlight_col = 1, 1

    try:
        date_font = ImageFont.truetype("/System/Library/Fonts/SFNSText.ttf",
                                       int(size * 0.08))
    except (OSError, IOError):
        try:
            date_font = ImageFont.truetype(
                "/System/Library/Fonts/Helvetica.ttc", int(size * 0.08))
        except (OSError, IOError):
            date_font = ImageFont.load_default()

    for row in range(rows):
        for col in range(cols):
            cx = grid_left + col * cell_w + cell_w // 2
            cy = grid_top + row * cell_h + cell_h // 2

            date_str = str(dates[row][col])

            if row == highlight_row and col == highlight_col:
                # Terracotta circle highlight
                circle_r = int(min(cell_w, cell_h) * 0.38)
                draw.ellipse(
                    [cx - circle_r, cy - circle_r,
                     cx + circle_r, cy + circle_r],
                    fill=terracotta,
                )
                # White text on terracotta
                bbox = draw.textbbox((0, 0), date_str, font=date_font)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
                draw.text(
                    (cx - tw // 2, cy - th // 2 - int(size * 0.01)),
                    date_str,
                    fill=white,
                    font=date_font,
                )
            else:
                # Regular date number
                bbox = draw.textbbox((0, 0), date_str, font=date_font)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
                color = text_dark if (row + col) % 3 != 0 else text_light
                draw.text(
                    (cx - tw // 2, cy - th // 2 - int(size * 0.01)),
                    date_str,
                    fill=color,
                    font=date_font,
                )

    return img


def main():
    output_path = (
        Path(__file__).resolve().parent.parent
        / "src" / "eventcalendar" / "resources" / "icon.png"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    icon = generate_icon(1024)
    icon.save(str(output_path), "PNG")
    print(f"Icon saved to {output_path}")


if __name__ == "__main__":
    main()
