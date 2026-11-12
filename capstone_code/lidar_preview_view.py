"""Tk projection of measured XYZ, without a floor model or safety classification."""
from itertools import product
import math
import tkinter as tk

try:
    from PIL import Image, ImageDraw, ImageTk
except ImportError:
    Image = ImageDraw = ImageTk = None

from lidar_preview import PreviewSnapshot

BACKGROUND = "#101b20"
VIEWS = ("front", "oblique", "top", "side")
POINT_RADIUS = 1.0
GRID_STEP_M = 0.1
DISPLAY_ZOOM = 5.0


def project_xyz(point, view="front"):
    x, y, z = point
    if view == "front":
        # Mirror horizontal movement in the front display.
        return y, -z, x
    if view == "top":
        return -y, -x, z
    if view == "side":
        return x, -z, -y
    return -0.86 * y + 0.50 * x, -0.35 * x - 0.94 * z, x + 0.2 * y + 0.1 * z


def fixed_projection(width, height, view, full_view=False, grid_step_m=GRID_STEP_M):
    """Fit a fixed sensor volume, never the current cloud's changing extents."""
    corners = [project_xyz(p, view) for p in product((0, 2), (-2, 2), (-2, 2) if full_view else (-1.2, 1.2))]
    xmin, xmax = min(p[0] for p in corners), max(p[0] for p in corners)
    ymin, ymax = min(p[1] for p in corners), max(p[1] for p in corners)
    scale = min(max(1, width - 48) / (xmax - xmin),
                max(1, height - 82) / (ymax - ymin))
    zoom = 1 if full_view else DISPLAY_ZOOM * GRID_STEP_M / grid_step_m
    return scale * zoom, (xmin + xmax) / 2, (ymin + ymax) / 2


def _distance_palette():
    # Fixed closer stops give nearby objects contrast without per-frame colour shifts.
    stops = ((0, (143, 99, 255)), (100, (75, 150, 255)), (200, (0, 216, 239)),
             (350, (73, 226, 157)), (600, (246, 223, 114)),
             (1000, (255, 155, 84)), (2000, (240, 114, 182)))
    colors = []
    for (start, first), (end, last) in zip(stops, stops[1:]):
        for millimeters in range(start, end):
            ratio = (millimeters - start) / (end - start)
            colors.append("#" + "".join(f"{round(a + (b - a) * ratio):02x}"
                                       for a, b in zip(first, last)))
    colors.append("#f072b6")
    return tuple(colors)


DISTANCE_COLORS = _distance_palette()


def distance_color(distance):
    return DISTANCE_COLORS[round(min(2.0, max(0.0, distance)) * 1000)]


def height_color(z):
    # Height colours are separate from the safety severity colours.
    low, middle, high = (75, 151, 255), (222, 230, 238), (255, 166, 79)
    ratio = min(1.0, abs(z))
    edge = low if z < 0 else high
    rgb = [round(middle[i] + (edge[i] - middle[i]) * ratio) for i in range(3)]
    return "#" + "".join(f"{v:02x}" for v in rgb)


class Lidar3DPreview(tk.Canvas):
    def __init__(self, parent):
        super().__init__(parent, bg=BACKGROUND, width=260, height=172, highlightthickness=0)
        self.view = "front"
        self.full_view = False
        self.grid_step_m = GRID_STEP_M
        self._snapshot = PreviewSnapshot()
        self.bind("<Configure>", lambda _e: self._draw())

    def update_snapshot(self, snapshot):
        if snapshot != self._snapshot:
            self._snapshot = snapshot
            self._draw()

    def set_view(self, view):
        if view not in VIEWS:
            raise ValueError("Unknown 3D view")
        self.view = view
        self._draw()

    def set_full_view(self, enabled):
        self.full_view = bool(enabled)
        self._draw()

    def set_grid_size_cm(self, centimeters):
        if centimeters not in (1, 5, 10):
            raise ValueError("Grid size must be 1, 5 or 10 cm")
        self.grid_step_m = centimeters / 100
        self.full_view = False
        self._draw()

    def _draw(self):
        self.delete("all")
        self._cloud_image = None
        w, h = self.winfo_width(), self.winfo_height()
        if w < 20 or h < 60:
            return
        snapshot = self._snapshot
        full_view = self.__dict__.get("full_view", False)
        selected_step = self.__dict__.get("grid_step_m", GRID_STEP_M)
        heading = "모의 3D" if snapshot.simulated else "3D 측정점"
        name = {"front": "정면", "oblique": "사선", "top": "위", "side": "옆"}[self.view]
        scale, cx, cy = fixed_projection(w, h, self.view, full_view, selected_step)

        def screen(projected_point):
            u, v, _ = projected_point
            return w / 2 + (u - cx) * scale, h / 2 + (v - cy) * scale

        # These are screen-plane metric guides, not inferred floor returns.
        left, right, top, bottom = 24, w - 24, 35, h - 35
        umin, umax = (cx + (edge - w / 2) / scale for edge in (left, right))
        vmin, vmax = (cy + (edge - h / 2) / scale for edge in (top, bottom))
        grid_step = .5 if full_view else selected_step
        for index in range(math.ceil(umin / grid_step), math.floor(umax / grid_step) + 1):
            px, _ = screen((index * grid_step, 0, 0))
            self.create_line(px, top, px, bottom, fill="#203038", tags="guide")
        for index in range(math.ceil(vmin / grid_step), math.floor(vmax / grid_step) + 1):
            _, py = screen((0, index * grid_step, 0))
            self.create_line(left, py, right, py, fill="#203038", tags="guide")
        bar = grid_step * scale
        self.create_line(16, h - 15, 16 + bar, h - 15,
                         fill="#bacad2", width=2, tags="scale")
        self.create_text(16, h - 25, text=f"한 칸 {grid_step * 100:g} cm", anchor=tk.W,
                         fill="#bacad2", font=("Segoe UI", 8))
        messages = {"missing": "3D 데이터 없음", "stale": "3D 수신 중단",
                    "empty": "유효 측정점 없음", "unavailable": "3D 연결 확인 필요"}
        if snapshot.status != "live":
            self.create_text(w / 2, 11, text=f"{heading} · {name} · 표시 거리 ≤ 2 m",
                             fill="#bacad2", font=("Segoe UI", 9))
            self.create_text(w / 2, h / 2, text=messages.get(snapshot.status, "3D 데이터 없음"),
                             fill="#ffad55" if snapshot.status in ("stale", "unavailable") else "#bacad2",
                             font=("Segoe UI", 10, "bold"))
            return
        projected = [(project_xyz(point, self.view), point) for point in snapshot.points]
        # One bitmap avoids thousands of Tcl calls for the denser local USB view.
        bitmap = Image.new("RGBA", (w, h)) if Image is not None and len(projected) > 256 else None
        brush = ImageDraw.Draw(bitmap) if bitmap is not None else None
        drawn_points = 0
        for projected_point, point in sorted(projected, key=lambda item: item[0][2], reverse=True):
            px, py = screen(projected_point)
            if not (left + POINT_RADIUS <= px <= right - POINT_RADIUS and
                    top + POINT_RADIUS <= py <= bottom - POINT_RADIUS):
                continue
            drawn_points += 1
            color = distance_color(math.sqrt(sum(value * value for value in point)))
            if brush is not None:
                ix, iy = round(px), round(py)
                brush.rectangle((ix - 1, iy - 1, ix, iy), fill=color)
            else:
                self.create_oval(px - POINT_RADIUS, py - POINT_RADIUS,
                                 px + POINT_RADIUS, py + POINT_RADIUS,
                                 fill=color, outline="", tags="point3d")
        if bitmap is not None:
            self._cloud_image = ImageTk.PhotoImage(bitmap, master=self)
            self.create_image(0, 0, anchor=tk.NW, image=self._cloud_image, tags="pointcloud3d")
        self.drawn_points, self.total_points = drawn_points, len(snapshot.points)
        if not drawn_points and snapshot.points:
            self.create_text(w / 2, h / 2, text="측정점이 확대 화면 밖에 있습니다",
                             fill="#bacad2", font=("Segoe UI", 10))
        self.create_text(w / 2, 11, text=f"{heading} · {name} · 화면 {drawn_points:,}/{len(snapshot.points):,}점",
                         fill="#bacad2", font=("Segoe UI", 9))
