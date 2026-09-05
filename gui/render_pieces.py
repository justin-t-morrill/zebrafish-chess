"""Render the bundled Lichess SVG piece theme to GUI-ready PNG files."""

from pathlib import Path

from reportlab.graphics import renderPM
from PIL import Image
from svglib.svglib import svg2rlg


ROOT = Path(__file__).resolve().parent / "assets"
NAMES = {
    "wK": "white_king", "wQ": "white_queen", "wR": "white_rook",
    "wB": "white_bishop", "wN": "white_knight", "wP": "white_pawn",
    "bK": "black_king", "bQ": "black_queen", "bR": "black_rook",
    "bB": "black_bishop", "bN": "black_knight", "bP": "black_pawn",
}


for source, destination in NAMES.items():
    for size in (64, 256):
        rendered = []
        for suffix, background in (("black", 0x000000), ("white", 0xFFFFFF)):
            drawing = svg2rlg(str(ROOT / "lichess_cburnett" / f"{source}.svg"))
            drawing.scale(size / drawing.width, size / drawing.height)
            drawing.width = size
            drawing.height = size
            path = ROOT / f".{destination}_{size}_{suffix}.png"
            renderPM.drawToFile(drawing, str(path), fmt="PNG", bg=background)
            rendered.append(path)

        # Recover true alpha from the same antialiased image rendered over black
        # and white. This keeps white piece interiors opaque while removing only
        # the SVG canvas background.
        black = Image.open(rendered[0]).convert("RGB")
        white = Image.open(rendered[1]).convert("RGB")
        output = Image.new("RGBA", black.size)
        pixels = []
        for black_pixel, white_pixel in zip(black.getdata(), white.getdata()):
            alpha = 255 - round(sum(w - b for b, w in zip(black_pixel, white_pixel)) / 3)
            alpha = max(0, min(255, alpha))
            if alpha:
                rgb = tuple(max(0, min(255, round(channel * 255 / alpha)))
                            for channel in black_pixel)
            else:
                rgb = (0, 0, 0)
            pixels.append((*rgb, alpha))
        output.putdata(pixels)
        output.save(ROOT / f"{destination}_modern_{size}x{size}.png")
        for path in rendered:
            path.unlink()
