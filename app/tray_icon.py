"""Small racing-style icon shared by the tray and Windows executable."""

from __future__ import annotations

from PIL import Image, ImageDraw


def create_tray_image(size: int = 64) -> Image.Image:
    image = Image.new("RGBA", (size, size), (13, 15, 18, 255))
    draw = ImageDraw.Draw(image)
    scale = size / 64

    # A simple tachometer shape stays readable at tray-icon size.
    draw.arc(
        (8 * scale, 8 * scale, 56 * scale, 56 * scale),
        155,
        385,
        fill=(242, 178, 0, 255),
        width=max(2, round(5 * scale)),
    )
    draw.line(
        (32 * scale, 34 * scale, 47 * scale, 20 * scale),
        fill=(245, 247, 250, 255),
        width=max(2, round(4 * scale)),
    )
    draw.ellipse(
        (28 * scale, 30 * scale, 36 * scale, 38 * scale),
        fill=(242, 178, 0, 255),
    )
    draw.rounded_rectangle(
        (16 * scale, 48 * scale, 48 * scale, 55 * scale),
        radius=2 * scale,
        fill=(245, 247, 250, 255),
    )
    return image
