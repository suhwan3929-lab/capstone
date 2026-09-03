"""
보호자 알림 (Discord Webhook)

이전 버전 대비 수정:
  [H1] URL 하드코딩 제거 → 환경변수 + 실제로 동작하는 유효성 검사
       (예전 `if not URL:` 은 플레이스홀더 문자열이 truthy라 절대 발동하지 않았다)
  [H2] 2단 전송 — 충격 감지 즉시 '예비 알림', 판정 후 '확정/취소 알림'
       지도 이미지는 텍스트 발송 '이후'에 따로 붙인다.
       예전에는 지도를 먼저 받느라 신고가 최대 10초 밀렸다.
  [H7] 측위 품질 / 위성 수 / HDOP / 좌표 신선도를 함께 보낸다.
       보호자에게 "오차 ±2 cm"와 "오차 ±5 m"는 완전히 다른 정보다.
  [⑧] 실패 시 지수 백오프 재시도 + 오프라인 큐잉

⚠ 어떤 경우에도 웹훅 URL을 로그에 출력하지 않는다.
"""
import json
import os
import pathlib
import queue
import threading
import time
from datetime import datetime, timezone

import config
from schema import GpsFix, ImuSample
from states import fix_quality_name

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    # requests가 없어도 판정 로직은 살아 있어야 한다.
    # 알림만 비활성화되고 나머지는 정상 동작한다.
    REQUESTS_AVAILABLE = False

_q: "queue.Queue[dict]" = queue.Queue(maxsize=64)
_log = None
_started = False
_spool_lock = threading.Lock()

KIND_PRELIM = "preliminary"
KIND_CONFIRM = "confirmed"
KIND_CANCEL = "cancelled"

#: 재시도해도 의미가 있는 알림. 예비/해제 알림은 시간이 지나면 가치가 없다.
DURABLE_KINDS = (KIND_CONFIRM,)


def _emit(msg, level="INFO"):
    if _log:
        _log(f"[알림] {msg}", level)


# ══════════════════════════════════════════════════════════
# 공개 API
# ══════════════════════════════════════════════════════════
def is_configured() -> bool:
    """[H1] 플레이스홀더에 속지 않는 진짜 검사."""
    if not REQUESTS_AVAILABLE:
        return False
    u = config.WEBHOOK_URL
    return u.startswith("https://discord.com/api/webhooks/") and len(u) > 50


def start(log_callback=None):
    global _log, _started
    _log = log_callback
    if not REQUESTS_AVAILABLE:
        _emit("⚠ requests 미설치 — 외부 알림 비활성화 "
              "(pip install requests)", "ERROR")
    elif not is_configured():
        _emit("⚠ WALKER_WEBHOOK_URL 환경변수가 없거나 형식이 올바르지 않습니다. "
              "외부 알림이 비활성화됩니다.", "ERROR")
    if not _started:
        _started = True
        _restore_spool()
        threading.Thread(target=_worker, daemon=True, name="Notifier").start()


def send_preliminary(imu: ImuSample, gps: GpsFix, age: float):
    """[H2] 충격 감지 즉시. 보호자가 이 시점부터 이동을 시작할 수 있다."""
    _enqueue(KIND_PRELIM, imu, gps, age)


def send_confirmed(imu: ImuSample, gps: GpsFix, age: float, peak_g: float):
    _enqueue(KIND_CONFIRM, imu, gps, age, peak_g=peak_g)


def send_cancelled(reason: str):
    _enqueue(KIND_CANCEL, None, None, None, reason=reason)


def pending() -> int:
    return _q.qsize()


# ══════════════════════════════════════════════════════════
# 내부
# ══════════════════════════════════════════════════════════
def _enqueue(kind, imu, gps, age, peak_g=None, reason=None):
    item = {
        "kind": kind,
        "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "peak_g": peak_g if peak_g is not None else (imu.accel_g if imu else None),
        "tilt_deg": imu.tilt_deg if imu else None,
        "lat": gps.lat if gps else None,
        "lon": gps.lon if gps else None,
        "fix_quality": gps.fix_quality if gps else 0,
        "satellites": gps.satellites if gps else 0,
        "hdop": gps.hdop if gps else None,
        "gps_utc": gps.utc if gps else None,
        "age": age,
        "reason": reason,
    }
    # 사고 확정 알림은 프로세스가 죽어도 살아남아야 한다 → 먼저 디스크에 남긴다
    if kind in DURABLE_KINDS:
        item["id"] = f"{time.time():.3f}-{kind}"
        _spool_add(item)

    try:
        _q.put_nowait(item)
    except queue.Full:
        _emit("전송 큐 포화 — 가장 오래된 항목 폐기", "ERROR")
        try:
            _q.get_nowait()
            _q.put_nowait(item)
        except queue.Empty:
            pass


def _worker():
    while True:
        item = _q.get()
        try:
            _deliver(item)
        except Exception as e:
            _emit(f"전송 처리 중 예외: {type(e).__name__}", "ERROR")
        finally:
            _q.task_done()


def _deliver(item):
    if not is_configured():
        return
    # 1단계: 텍스트를 먼저 보낸다 (지도를 기다리지 않는다) [H2]
    ok = _post_with_retry(_build_payload(item))
    if not ok:
        _emit("재시도 소진 — 전송 실패. "
              "다음 기동 시 재시도합니다." if item.get("id") else
              "재시도 소진 — 전송 실패", "ERROR")
        return
    _emit(f"보호자 알림 전송 성공 ({item['kind']})", "INFO")
    if item.get("id"):
        _spool_remove(item["id"])

    # 2단계: 확정 알림에 한해 지도 이미지를 후속 첨부
    if item["kind"] == KIND_CONFIRM and item["lat"] is not None:
        img = _fetch_static_map(item["lat"], item["lon"])
        if img:
            _post_image(img, item)


# ══════════════════════════════════════════════════════════
# 디스크 스풀 — 재부팅/크래시에도 사고 알림이 사라지지 않게 한다
#
# LTE가 끊긴 순간에 사고가 나고 그대로 프로세스가 죽으면,
# 메모리 큐만 있는 구조에서는 그 알림이 영영 사라진다.
# 사고 알림은 다시 만들 수 없는 정보이므로 디스크에 남긴다.
# ══════════════════════════════════════════════════════════
def _spool_path():
    p = pathlib.Path(config.NOTIFY_SPOOL)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _spool_add(item):
    try:
        with _spool_lock, open(_spool_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())        # 전원이 끊겨도 남도록 강제 반영
    except Exception as e:
        _emit(f"스풀 기록 실패: {type(e).__name__}", "WARN")


def _spool_remove(item_id):
    try:
        with _spool_lock:
            p = _spool_path()
            if not p.exists():
                return
            keep = []
            for line in p.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    if json.loads(line).get("id") != item_id:
                        keep.append(line)
                except json.JSONDecodeError:
                    continue
            p.write_text("\n".join(keep) + ("\n" if keep else ""),
                         encoding="utf-8")
    except Exception as e:
        _emit(f"스풀 정리 실패: {type(e).__name__}", "WARN")


def _restore_spool():
    """기동 시 미전송 알림을 큐에 되살린다."""
    try:
        p = _spool_path()
        if not p.exists():
            return
        items = []
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        items = items[-config.NOTIFY_SPOOL_MAX:]
        if not items:
            return
        _emit(f"미전송 알림 {len(items)}건을 이어서 전송합니다", "WARN")
        for it in items:
            it["late"] = True           # 지연 발송임을 메시지에 표시
            try:
                _q.put_nowait(it)
            except queue.Full:
                break
    except Exception as e:
        _emit(f"스풀 복구 실패: {type(e).__name__}", "WARN")


def _post_with_retry(payload) -> bool:
    delay = 1.0
    for attempt in range(config.WEBHOOK_MAX_RETRY):
        try:
            r = requests.post(config.WEBHOOK_URL, json=payload,
                              timeout=config.WEBHOOK_TIMEOUT)
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After", 5)))
                continue
            if r.ok or r.status_code == 204:
                return True
            _emit(f"응답 코드 {r.status_code} (재시도 {attempt + 1})", "WARN")
        except Exception as e:
            # ⚠ URL은 절대 로그에 남기지 않는다
            _emit(f"전송 실패 {type(e).__name__} — {delay:.0f}초 후 재시도", "WARN")
        time.sleep(delay)
        delay = min(delay * 2, 60.0)
    return False


def _post_image(image_bytes, item):
    try:
        files = {
            "file": ("map.png", image_bytes, "image/png"),
            "payload_json": (None, json.dumps(
                {"content": "📍 사고 지점 지도"}), "application/json"),
        }
        requests.post(config.WEBHOOK_URL, files=files,
                      timeout=config.WEBHOOK_TIMEOUT * 2)
    except Exception:
        pass        # 지도는 부가정보 — 실패해도 무시


def _fetch_static_map(lat, lon):
    try:
        url = ("https://staticmap.openstreetmap.de/staticmap.php"
               f"?center={lat},{lon}&zoom=16&size=600x400"
               f"&markers={lat},{lon},red-pushpin")
        r = requests.get(url, timeout=config.MAP_FETCH_TIMEOUT)
        return r.content if r.status_code == 200 and r.content else None
    except Exception:
        return None


def _build_payload(item):
    kind = item["kind"]
    header = {
        KIND_PRELIM:  ("⚠️ **[예비] 강한 충격 감지**", 16753920,
                       "판정 중입니다. 확정/해제 알림이 곧 이어집니다."),
        KIND_CONFIRM: ("🚨 **[확정] 사고 발생**", 16711680,
                       "사용자가 응답하지 않았거나 사고를 확인했습니다."),
        KIND_CANCEL:  ("✅ **[해제] 사고 아님**", 65280,
                       item.get("reason") or "정상 상태로 복귀했습니다."),
    }[kind]
    title, color, desc = header

    if item.get("late"):
        # 통신 두절로 지연 발송된 알림임을 반드시 알린다.
        # 보호자가 '방금 일어난 일'로 오해하면 안 된다.
        title = "⏱ " + title + "  (지연 발송)"
        desc = ("⚠ 통신 두절로 발송이 지연되었습니다. "
                "아래 시각은 **사고 발생 시각**입니다.\n" + desc)

    fields = [{"name": "🕒 시각 (UTC)", "value": item["utc"], "inline": True}]

    if item["peak_g"] is not None:
        fields.append({"name": "💥 충격량",
                       "value": f"{item['peak_g']:.2f} G", "inline": True})
    if item["tilt_deg"] is not None:
        fields.append({"name": "📐 기울기",
                       "value": f"{item['tilt_deg']:.0f}°", "inline": True})

    if kind != KIND_CANCEL:
        if item["lat"] is not None:
            # [H7] 좌표만 주지 말고 '얼마나 믿을 수 있는지'를 함께 준다
            q = fix_quality_name(item["fix_quality"])
            hdop = f"{item['hdop']:.1f}" if item["hdop"] is not None else "-"
            age = item["age"]
            age_txt = "실시간" if age is not None and age < 3 else \
                      (f"{age:.0f}초 전 좌표" if age is not None else "알 수 없음")
            fields += [
                {"name": "📍 위치",
                 "value": f"{item['lat']:.7f}, {item['lon']:.7f}", "inline": False},
                {"name": "🛰️ 측위 품질",
                 "value": f"{q} / 위성 {item['satellites']}개 / HDOP {hdop}",
                 "inline": True},
                {"name": "⏱️ 좌표 신선도", "value": age_txt, "inline": True},
                {"name": "🗺️ 지도",
                 "value": f"https://www.openstreetmap.org/?mlat={item['lat']}"
                          f"&mlon={item['lon']}#map=18/{item['lat']}/{item['lon']}",
                 "inline": False},
            ]
        else:
            fields.append({"name": "📍 위치",
                           "value": "⚠ 측위 미확보 — 위치를 알 수 없습니다",
                           "inline": False})

    return {
        "content": title,
        "embeds": [{
            "title": "고령자 보행기 안전 시스템",
            "description": desc,
            "color": color,
            "fields": fields,
            "footer": {"text": "자동 발송 · 의료기기가 아닌 보조 장치입니다"},
        }],
    }
