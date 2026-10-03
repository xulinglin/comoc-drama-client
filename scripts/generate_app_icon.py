"""生成客户端 app-icon.ico / app-icon.png。

设计来源：comic-drama-vue/src/assets/cdtv-icon.svg
- 深色圆角底
- 内层细描边（白色 10% 透明叠在深底上的近似色）
- 左右两段弧（青/粉），合成一个圆并留上下开口
- 中央播放三角（黄）
- 四角圆点（黄/青/粉/白）
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent.parent
ASSET_DIR = ROOT / "assets"
PNG_PATH = ASSET_DIR / "app-icon.png"
ICO_PATH = ASSET_DIR / "app-icon.ico"

# 颜色（与 Vue 端 cdtv-icon.svg 保持一致）
BG = (15, 18, 28, 255)             # #0f121c
INNER_STROKE = (39, 42, 51, 255)   # 白色 10% 透明叠在深底色上的近似色
CYAN = (46, 221, 255, 255)         # #2eddff
PINK = (255, 63, 168, 255)         # #ff3fa8
YELLOW = (255, 218, 90, 255)       # #ffda5a
WHITE = (246, 248, 255, 255)       # #f6f8ff

SIZE = 1024


def _point_on_arc(center, radius, angle_deg):
    """PIL 角度约定：0=3 点钟方向，逆时针递增（y 轴向下时视觉上为逆时针）。"""
    rad = math.radians(angle_deg)
    x = center[0] + radius * math.cos(rad)
    y = center[1] - radius * math.sin(rad)
    return x, y


def _draw_arc(draw, center, radius, start, end, color, width):
    """画弧并在两端补圆点，模拟 SVG 的 stroke-linecap="round"。"""
    bbox = (center[0] - radius, center[1] - radius,
            center[0] + radius, center[1] + radius)
    draw.arc(bbox, start=start, end=end, fill=color, width=width)
    cap_r = width // 2
    for angle in (start, end):
        x, y = _point_on_arc(center, radius, angle)
        draw.ellipse((x - cap_r, y - cap_r, x + cap_r, y + cap_r), fill=color)


def create_icon() -> None:
    ASSET_DIR.mkdir(exist_ok=True)
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # 1. 外层深色圆角背景
    draw.rounded_rectangle((64, 64, 960, 960), radius=220, fill=BG)

    # 2. 内层细描边（白色 10% 透明，近似为深底色加亮）
    draw.rounded_rectangle(
        (132, 214, 892, 814),
        radius=120,
        outline=INNER_STROKE,
        width=12,
    )

    # 3. 左右两段弧（合成一个圆，留上下开口）
    #    SVG 弧的圆心 (478, 511.5)，半径 231
    arc_center = (478, 511)
    arc_radius = 231
    # 青弧：左半边，端点 (421,285) 与 (421,738)
    _draw_arc(draw, arc_center, arc_radius, 104, 256, CYAN, 78)
    # 粉弧：右半边，端点 (535,738) 与 (535,285)
    _draw_arc(draw, arc_center, arc_radius, 284, 436, PINK, 78)

    # 4. 中央播放三角
    draw.polygon([(555, 425), (555, 605), (708, 515)], fill=YELLOW)

    # 5. 四角点缀
    draw.ellipse((228, 256, 264, 292), fill=YELLOW)   # (246,274) r=18
    draw.ellipse((770, 288, 798, 316), fill=CYAN)     # (784,302) r=14
    draw.ellipse((792, 716, 828, 752), fill=PINK)     # (810,734) r=18
    draw.ellipse((214, 752, 238, 776), fill=WHITE)    # (226,764) r=12

    image = image.resize((256, 256), Image.Resampling.LANCZOS)
    image.save(PNG_PATH)
    image.save(ICO_PATH, sizes=[(16, 16), (24, 24), (32, 32),
                                (48, 48), (64, 64), (128, 128), (256, 256)])


if __name__ == "__main__":
    create_icon()
    print(f"已生成: {PNG_PATH}")
    print(f"已生成: {ICO_PATH}")
