"""TkinterMapView의 기본 네트워크 요청과 사전 다운로드를 사용하지 않는다."""
import io
import math

from PIL import Image, ImageTk
from tkintermapview import TkinterMapView

from map_tiles import TileClient


class WalkerMapView(TkinterMapView):
    def __init__(self, master, *, cache_path, tile_url, status_callback, **kwargs):
        self.tile_client = TileClient(cache_path, tile_url)
        self.tiles_enabled = False
        self._map_visible = False
        self._status_callback = status_callback
        super().__init__(master, **kwargs)
        self.tile_server = tile_url
        self.bind("<Map>", self._shown, add="+")
        self.bind("<Unmap>", self._hidden, add="+")
        self._status_job = self.after(1000, self._poll_status)

    def pre_cache(self):
        # 기본 라이브러리의 화면 밖 타일 사전 요청을 중단한다.
        return

    def request_image(self, zoom, x, y, db_cursor=None):
        if (not self.tiles_enabled or not self._map_visible or not self.running
                or zoom != round(self.zoom)):
            return self.empty_tile_image
        left, top = self.upper_left_tile_pos
        right, bottom = self.lower_right_tile_pos
        if not (math.floor(left) <= x <= math.floor(right)
                and math.floor(top) <= y <= math.floor(bottom)):
            return self.empty_tile_image
        data = self.tile_client.get_tile(zoom, x, y)
        if data is None or not self.running:
            return self.empty_tile_image
        try:
            with Image.open(io.BytesIO(data)) as image:
                tile = ImageTk.PhotoImage(image, master=self)
            self.tile_image_cache[f"{zoom}{x}{y}"] = tile
            return tile
        except (OSError, RuntimeError):
            return self.empty_tile_image

    def set_gps_position(self, lat, lon):
        if not self.tiles_enabled:
            # 기본 라이브러리의 초기 좌표 대신 실제 GPS 위치에서만 요청을 시작한다.
            self.set_position(lat, lon)
            self.tiles_enabled = True
            self.set_tile_server(self.tile_client.tile_url)
        else:
            self.set_position(lat, lon)

    def _shown(self, event=None):
        self._map_visible = True
        if self.tiles_enabled:
            self.set_tile_server(self.tile_client.tile_url)

    def _hidden(self, event=None):
        self._map_visible = False

    def pause(self):
        self.tiles_enabled = False

    def _poll_status(self):
        if not self.running:
            return
        self._status_callback(self.tile_client.status())
        if self.tiles_enabled and self.winfo_ismapped() and self.tile_client.retry_due():
            self.set_tile_server(self.tile_client.tile_url)
        self._status_job = self.after(1000, self._poll_status)

    def destroy(self):
        self.after_cancel(self._status_job)
        super().destroy()
