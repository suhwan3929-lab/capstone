"""화면에 필요한 지도 타일을 식별 가능한 요청과 재사용 가능한 캐시로 읽는다."""
import io
import re
import sqlite3
import threading
import time
from contextlib import closing
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests
from PIL import Image

TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
USER_AGENT = "CapstoneWalkerSafety/1.0 (+https://github.com/suhwan3929-lab/capstone)"
DEFAULT_TTL = 7 * 86400


class TileClient:
    def __init__(self, cache_path, tile_url=TILE_URL, http=None, clock=time.time):
        if not tile_url.startswith("https://") or not all(
                field in tile_url for field in ("{z}", "{x}", "{y}")):
            raise ValueError("지도 서버는 z/x/y 형식의 HTTPS 주소여야 합니다")
        self.tile_url = tile_url
        self.cache_path = Path(cache_path)
        self.http = http or requests.Session()
        self.clock = clock
        self._lock = threading.RLock()  # 같은 타일 중복 요청과 HTTP 동시 요청을 막는다.
        self._memory = {}
        self.state = "waiting"
        self.retry_at = 0.0

    def _read(self, url):
        if url in self._memory:
            return self._memory[url]
        if not self.cache_path.is_file():
            return None
        try:
            with closing(sqlite3.connect(self.cache_path, timeout=1)) as db:
                row = db.execute("SELECT data,expires,etag,modified FROM tiles WHERE url=?", (url,)).fetchone()
            if row:
                self._validate(row[0])
                return row
        except (OSError, sqlite3.Error, ValueError):
            pass
        return None

    def _write(self, url, entry):
        self._memory[url] = entry
        if len(self._memory) > 512:
            self._memory.pop(next(iter(self._memory)))
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.cache_path, timeout=1)) as db, db:
                db.execute("CREATE TABLE IF NOT EXISTS tiles "
                           "(url TEXT PRIMARY KEY,data BLOB,expires REAL,etag TEXT,modified TEXT)")
                db.execute("INSERT OR REPLACE INTO tiles VALUES (?,?,?,?,?)", (url, *entry))
        except (OSError, sqlite3.Error):
            pass  # 캐시 디스크 오류가 GPS 좌표 표시를 중단시키지 않는다.

    @staticmethod
    def _validate(data):
        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.format != "PNG" or image.size != (256, 256):
                    raise ValueError("invalid tile")
                image.verify()
        except Exception as exc:
            raise ValueError("invalid tile") from exc

    def _expiry(self, headers, now):
        control = headers.get("Cache-Control", "").lower()
        if "no-store" in control:
            return None
        if "no-cache" in control:
            return now
        match = re.search(r"(?:^|,)\s*max-age\s*=\s*\"?(\d+)", control)
        if match:
            try:
                age = max(0, int(headers.get("Age", "0")))
            except ValueError:
                age = 0
            return now + max(0, int(match.group(1)) - age)
        try:
            return parsedate_to_datetime(headers["Expires"]).timestamp()
        except (KeyError, TypeError, ValueError, OverflowError):
            return now + DEFAULT_TTL

    def get_tile(self, zoom, x, y):
        if not (type(zoom) is int and 0 <= zoom <= 19 and 0 <= y < 2 ** zoom):
            return None
        url = self.tile_url.format(z=zoom, x=x % (2 ** zoom), y=y)
        with self._lock:
            now = self.clock()
            cached = self._read(url)
            if cached and now < cached[1]:
                if self.state not in ("blocked", "offline"):
                    self.state = "ready"
                return cached[0]
            if now < self.retry_at:
                return cached[0] if cached else None
            headers = {"User-Agent": USER_AGENT, "Accept": "image/png"}
            if cached:
                if cached[2]:
                    headers["If-None-Match"] = cached[2]
                if cached[3]:
                    headers["If-Modified-Since"] = cached[3]
            response = None
            try:
                response = self.http.get(url, headers=headers, timeout=(3, 6), allow_redirects=False)
                if response.status_code in (403, 429):
                    self.state = "blocked"
                    delay = 60
                    try:
                        delay = max(delay, int(response.headers.get("Retry-After", "60")))
                    except ValueError:
                        try:
                            delay = max(delay, parsedate_to_datetime(response.headers["Retry-After"]).timestamp() - now)
                        except (KeyError, TypeError, ValueError, OverflowError):
                            pass
                    self.retry_at = now + delay
                    return cached[0] if cached else None
                if response.status_code == 304 and cached:
                    data = cached[0]
                elif response.status_code == 200:
                    data = response.content
                    if len(data) > 1024 * 1024:
                        raise ValueError("oversized tile")
                    self._validate(data)
                else:
                    raise ValueError("tile request failed")
                expires = self._expiry(response.headers, now)
                if expires is not None:
                    self._write(url, (data, expires,
                                     response.headers.get("ETag", cached[2] if cached else ""),
                                     response.headers.get("Last-Modified", cached[3] if cached else "")))
                self.state, self.retry_at = "ready", 0.0
                return data
            except (requests.RequestException, ValueError, OSError):
                self.state, self.retry_at = "offline", now + 30
                return cached[0] if cached else None
            finally:
                if response is not None:
                    response.close()

    def status(self):
        return self.state  # HTTP 요청을 기다리며 GUI 스레드를 막지 않는다.

    def retry_due(self):
        if not self._lock.acquire(blocking=False):
            return False
        try:
            if self.retry_at and self.clock() >= self.retry_at:
                self.retry_at = 0.0
                self.state = "loading"
                return True
            return False
        finally:
            self._lock.release()
