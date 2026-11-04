"""센서/네트워크/알림 없이 LiDAR 카드 미리보기. 데이터는 모두 모의 값.

    python tools/preview_lidar_ui.py
    python tools/preview_lidar_ui.py --output docs/images/lidar_preview.png

PNG 저장 옵션만 Pillow가 필요하다.
"""
import argparse
import math
from pathlib import Path
import sys
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ui


def sample_points(distance):
    points = []
    for i in range(32):
        angle = math.radians(-39 + i * 78 / 31)
        # 중앙 물체와 그 뒤 벽을 표현하는 모의 윤곽.
        x = distance if abs(angle) < 0.25 else 3.0 + 0.15 * math.cos(angle * 4)
        points.append([round(x, 3), round(x * math.tan(angle), 3)])
    return points


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = tk.Tk()
    root.title("LiDAR 윤곽 미리보기 — 모의 데이터")
    root.configure(bg=ui.C_BG)
    root.geometry("1280x360+100+100")
    root.minsize(1024, 360)
    tk.Label(root, text="LiDAR 윤곽 미리보기 · 모의 데이터", bg=ui.C_BG,
             fg=ui.C_BLUE, font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=16, pady=10)
    body = tk.Frame(root, bg=ui.C_BG)
    body.pack(fill=tk.BOTH, expand=True, padx=14)
    body.columnconfigure(0, weight=1, uniform="cards")
    body.columnconfigure(1, weight=1, uniform="cards")
    body.rowconfigure(0, weight=1)
    left, right = ui.LidarCard(body, "Left LiDAR"), ui.LidarCard(body, "Right LiDAR")
    left.set_mode("2D")
    right.set_mode("2D")
    left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
    right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

    def show(mode):
        for card, distance in ((left, 0.65), (right, 1.2)):
            card.update_card(distance, mode != "sensor", mode != "link",
                             None if mode == "legacy" else [] if mode == "empty"
                             else sample_points(distance), simulated=True)

    controls = tk.Frame(root, bg=ui.C_BG)
    controls.pack(fill=tk.X, padx=14, pady=8)
    for text, mode in (("측정 예시", "points"), ("링크 끊김", "link"),
                       ("센서 응답 없음", "sensor"), ("거리만 수신", "legacy"),
                       ("유효 점 없음", "empty")):
        tk.Button(controls, text=text, command=lambda m=mode: show(m),
                  bg=ui.C_CARD, fg=ui.C_WHITE, relief=tk.FLAT).pack(side=tk.LEFT, padx=(0, 8))
    root.update()
    show("points")
    if args.output:
        def save():
            from PIL import ImageGrab
            root.update()
            x, y = root.winfo_rootx(), root.winfo_rooty()
            args.output.parent.mkdir(parents=True, exist_ok=True)
            ImageGrab.grab(bbox=(x, y, x+root.winfo_width(), y+root.winfo_height())).save(args.output)
            print(f"Saved: {args.output.resolve()}")
            root.destroy()
        root.after(400, save)
    root.mainloop()


if __name__ == "__main__":
    main()
