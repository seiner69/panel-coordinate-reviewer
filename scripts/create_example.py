from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "example" / "stream.png"


def main() -> None:
    image = Image.new("RGB", (320, 960), "#e8edf2")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    colors = ["#cfe8ff", "#ffe5bf", "#d8f2d2", "#ead9ff"]
    panels = [(24, 45, 296, 265), (12, 280, 308, 470), (35, 500, 285, 625), (32, 655, 288, 890)]
    for index, box in enumerate(panels, start=1):
        draw.rounded_rectangle(box, radius=18, fill=colors[(index - 1) % len(colors)], outline="#26384a", width=4)
        draw.text((box[0] + 14, box[1] + 14), f"SYNTHETIC PANEL {index}", fill="#17212b", font=font)
        center_x = (box[0] + box[2]) // 2
        center_y = (box[1] + box[3]) // 2
        draw.ellipse((center_x - 35, center_y - 35, center_x + 35, center_y + 35), outline="#375a7f", width=6)
        draw.line((box[0] + 25, box[3] - 35, box[2] - 25, box[3] - 35), fill="#375a7f", width=5)
    for y in (320, 640):
        draw.line((0, y, 320, y), fill="#00a6c7", width=3)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT, "PNG", optimize=True)
    print(OUTPUT)


if __name__ == "__main__":
    main()
