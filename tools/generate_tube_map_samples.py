"""Create deterministic 2D and 3D Tube Map sample visuals from the IRIS DB."""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "heat_exchanger_db3.db"
OUTPUT_DIR = ROOT / "static" / "report_samples"
WIDTH, HEIGHT = 1600, 900
NAVY = "#17365d"
INK = "#13222d"
MUTED = "#687983"
LINE = "#dce4e8"
NORMAL = "#14b8a6"
WARNING = "#f59e0b"
CRITICAL = "#ef4444"
NOT_INSPECTED = "#94a3b8"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "malgunbd.ttf" if bold else "malgun.ttf"
    return ImageFont.truetype(str(Path("C:/Windows/Fonts") / name), size)


def mix_color(first: str, second: str, ratio: float) -> str:
    ratio = max(0.0, min(1.0, ratio))
    a = tuple(int(first[i : i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(second[i : i + 2], 16) for i in (1, 3, 5))
    values = tuple(round(x + (y - x) * ratio) for x, y in zip(a, b))
    return "#" + "".join(f"{value:02x}" for value in values)


def loss_color(loss: float | None) -> str:
    if loss is None:
        return NOT_INSPECTED
    if loss <= 20:
        return mix_color(NORMAL, WARNING, loss / 20)
    return mix_color(WARNING, CRITICAL, (loss - 20) / 20)


def load_sample() -> tuple[str, int, list[dict]]:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    selected = connection.execute(
        """
        SELECT i.iris_inspection_id, e.equipment_code, COUNT(*) AS tube_count
          FROM iris_inspection i
          JOIN heat_exchanger h ON h.heat_exchanger_id = i.heat_exchanger_id
          JOIN equipment e ON e.equipment_id = h.equipment_id
          JOIN iris_tube_result r ON r.iris_inspection_id = i.iris_inspection_id
         WHERE r.wall_loss_percent IS NOT NULL
         GROUP BY i.iris_inspection_id, e.equipment_code
         ORDER BY tube_count DESC, i.iris_inspection_id DESC
         LIMIT 1
        """
    ).fetchone()
    rows = connection.execute(
        """
        SELECT r.source_tube_id AS tube_no, r.source_row AS row_no,
               r.source_column AS column_no, r.wall_loss_percent,
               r.minimum_wall_thickness_mm, r.corrosion_type,
               COALESCE(t.current_status, 'IN_SERVICE') AS current_status
          FROM iris_tube_result r
          LEFT JOIN heat_exchanger_tube t ON t.tube_id = r.tube_id
         WHERE r.iris_inspection_id = ?
         ORDER BY r.source_row, r.source_column, r.source_tube_id
        """,
        (selected["iris_inspection_id"],),
    ).fetchall()
    connection.close()
    return selected["equipment_code"], selected["iris_inspection_id"], [dict(row) for row in rows]


def rounded(draw: ImageDraw.ImageDraw, box, radius=16, fill="#ffffff", outline=LINE, width=2):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def header(draw: ImageDraw.ImageDraw, title: str, subtitle: str, active: str) -> None:
    draw.rectangle((0, 0, WIDTH, HEIGHT), fill="#eef3f5")
    draw.rectangle((0, 0, WIDTH, 76), fill=NAVY)
    draw.text((42, 20), "IRIS", font=font(28, True), fill="#ffffff")
    draw.text((140, 23), "지능형열교환기 시스템", font=font(22, True), fill="#e6eef7")
    rounded(draw, (32, 96, WIDTH - 32, HEIGHT - 30), radius=20)
    draw.text((62, 120), title, font=font(29, True), fill=INK)
    draw.text((62, 161), subtitle, font=font(17), fill=MUTED)
    x = 1110
    for label in ("2D", "3D"):
        selected = label == active
        rounded(draw, (x, 117, x + 100, 163), radius=9, fill=NAVY if selected else "#ffffff", outline=NAVY)
        tw = draw.textbbox((0, 0), label, font=font(18, True))[2]
        draw.text((x + (100 - tw) / 2, 127), label, font=font(18, True), fill="#ffffff" if selected else NAVY)
        x += 112
    draw.text((1360, 132), "감육률 색상", font=font(16, True), fill=INK)


def legend(draw: ImageDraw.ImageDraw, y: int) -> None:
    entries = [(NORMAL, "정상"), (WARNING, "주의"), (CRITICAL, "위험"), (NOT_INSPECTED, "미검사")]
    x = 905
    for color, label in entries:
        draw.ellipse((x, y, x + 18, y + 18), fill=color)
        draw.text((x + 26, y - 3), label, font=font(15), fill=MUTED)
        x += 126


def normalized_positions(tubes: list[dict]) -> list[tuple[dict, float, float]]:
    valid = [tube for tube in tubes if tube["row_no"] is not None and tube["column_no"] is not None]
    if not valid:
        return []
    min_row = min(tube["row_no"] for tube in valid)
    max_row = max(tube["row_no"] for tube in valid)
    min_col = min(tube["column_no"] for tube in valid)
    max_col = max(tube["column_no"] for tube in valid)
    row_span = max(max_row - min_row, 1)
    col_span = max(max_col - min_col, 1)
    return [
        (
            tube,
            (tube["column_no"] - min_col) / col_span,
            (tube["row_no"] - min_row) / row_span,
        )
        for tube in valid
    ]


def draw_2d(equipment: str, inspection_id: int, tubes: list[dict], output: Path) -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), "#ffffff")
    draw = ImageDraw.Draw(image)
    header(draw, "2D Tube Map", f"설비 {equipment} · 검사 ID {inspection_id} · 상부 기준 배열", "2D")
    legend(draw, 191)
    rounded(draw, (62, 222, 1130, 820), radius=14, fill="#f8fbfc")
    center_x, center_y, radius = 595, 520, 270
    draw.ellipse((center_x - radius, center_y - radius, center_x + radius, center_y + radius), fill="#edf3f4", outline="#cbd7dc", width=4)
    draw.ellipse((center_x - radius + 18, center_y - radius + 18, center_x + radius - 18, center_y + radius - 18), outline="#d8e2e6", width=2)
    positioned = normalized_positions(tubes)
    selected = max(tubes, key=lambda item: item["wall_loss_percent"] or -1)
    for tube, nx, ny in positioned:
        x = center_x + (nx - 0.5) * 470
        y = center_y + (ny - 0.5) * 470
        if math.hypot(x - center_x, y - center_y) > radius - 30:
            scale = (radius - 30) / math.hypot(x - center_x, y - center_y)
            x, y = center_x + (x - center_x) * scale, center_y + (y - center_y) * scale
        color = loss_color(tube["wall_loss_percent"])
        size = 14 if tube is not selected else 20
        draw.ellipse((x - size, y - size, x + size, y + size), fill=color, outline="#ffffff", width=3)
        if tube is selected:
            draw.ellipse((x - 27, y - 27, x + 27, y + 27), outline=NAVY, width=4)
            draw.line((x + 27, y - 15, 1187, 330), fill=NAVY, width=3)
    rounded(draw, (1165, 250, 1532, 700), radius=14, fill="#ffffff")
    draw.text((1192, 280), "선택 튜브", font=font(17, True), fill=MUTED)
    draw.text((1192, 316), f"Tube {selected['tube_no']}", font=font(28, True), fill=INK)
    values = [
        ("감육률", f"{selected['wall_loss_percent']:.1f}%"),
        ("최소 두께", f"{selected['minimum_wall_thickness_mm']:.2f} mm"),
        ("부식 유형", selected["corrosion_type"] or "미등록"),
        ("운전 상태", "사용 중" if selected["current_status"] == "IN_SERVICE" else selected["current_status"]),
    ]
    y = 385
    for label, value in values:
        draw.text((1192, y), label, font=font(15), fill=MUTED)
        draw.text((1192, y + 25), value, font=font(19, True), fill=INK)
        draw.line((1192, y + 61, 1502, y + 61), fill=LINE, width=2)
        y += 78
    draw.text((1180, 746), "색상은 감육률 기준이며 선택 튜브는 외곽선으로 강조됩니다.", font=font(13), fill=MUTED)
    image.save(output, quality=95)


def draw_cylinder(draw: ImageDraw.ImageDraw, x: float, y: float, height: float, color: str, selected: bool) -> None:
    half_w, half_h = 11, 5
    top_y = y - height
    shadow = "#c7d2d8"
    draw.ellipse((x - half_w + 5, y + 2, x + half_w + 7, y + 12), fill=shadow)
    side = mix_color(color, "#0f172a", 0.22)
    draw.rectangle((x - half_w, top_y, x + half_w, y), fill=side)
    draw.polygon([(x - half_w, top_y), (x, top_y - half_h), (x + half_w, top_y), (x, top_y + half_h)], fill=color)
    draw.ellipse((x - half_w, top_y - half_h, x + half_w, top_y + half_h), fill=color, outline="#ffffff", width=2)
    if selected:
        draw.ellipse((x - half_w - 7, top_y - half_h - 7, x + half_w + 7, top_y + half_h + 7), outline=NAVY, width=4)


def draw_3d(equipment: str, inspection_id: int, tubes: list[dict], output: Path) -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), "#ffffff")
    draw = ImageDraw.Draw(image)
    header(draw, "3D Tube Map", f"설비 {equipment} · 검사 ID {inspection_id} · 회전 및 개별 튜브 확인", "3D")
    legend(draw, 191)
    rounded(draw, (62, 222, 1220, 820), radius=14, fill="#f7fafb")
    draw.polygon([(190, 665), (600, 390), (1080, 610), (664, 794)], fill="#e4ecef", outline="#c3d0d5")
    positioned = normalized_positions(tubes)
    selected = max(tubes, key=lambda item: item["wall_loss_percent"] or -1)
    projected = []
    for tube, nx, ny in positioned:
        px = 235 + nx * 640 + ny * 285
        py = 640 - nx * 235 + ny * 115
        projected.append((py, px, tube))
    for py, px, tube in sorted(projected):
        loss = tube["wall_loss_percent"] or 0
        draw_cylinder(draw, px, py, 72 + min(loss, 60) * 1.5, loss_color(tube["wall_loss_percent"]), tube is selected)
    rounded(draw, (1250, 244, 1534, 735), radius=14, fill="#0f172a", outline="#334155")
    draw.text((1274, 270), "선택 튜브", font=font(16, True), fill="#93c5fd")
    draw.text((1274, 305), f"Tube {selected['tube_no']}", font=font(26, True), fill="#ffffff")
    values = [
        ("감육률", f"{selected['wall_loss_percent']:.1f}%"),
        ("최소 두께", f"{selected['minimum_wall_thickness_mm']:.2f} mm"),
        ("확대 축소", "마우스 휠"),
        ("회전", "드래그"),
        ("개별 이동", "Transform"),
    ]
    y = 370
    for label, value in values:
        draw.text((1274, y), label, font=font(14), fill="#94a3b8")
        draw.text((1274, y + 24), value, font=font(17, True), fill="#f8fafc")
        y += 68
    rounded(draw, (1270, 670, 1514, 715), radius=8, fill="#1e293b", outline="#526173")
    draw.text((1318, 681), "선택 해제", font=font(15, True), fill="#e2e8f0")
    draw.text((82, 786), "대표 화면 샘플 · 높이와 색상으로 감육 상태를 표현하고 선택 튜브만 회전 확대 이동할 수 있습니다.", font=font(14), fill=MUTED)
    image.save(output, quality=95)


def main() -> None:
    equipment, inspection_id, tubes = load_sample()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    draw_2d(equipment, inspection_id, tubes, OUTPUT_DIR / "tube_map_2d_sample.png")
    draw_3d(equipment, inspection_id, tubes, OUTPUT_DIR / "tube_map_3d_sample.png")
    print(OUTPUT_DIR / "tube_map_2d_sample.png")
    print(OUTPUT_DIR / "tube_map_3d_sample.png")


if __name__ == "__main__":
    main()
