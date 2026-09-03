"""
LiDAR 센서 모듈 (CygLiDAR D2)
- 터미널 로그 표출 강화 (검사 생략으로 오해하는 증상 해결)
"""

import threading
import time

try:
    import serial
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

try:
    import Jetson.GPIO as GPIO
    ON_JETSON = True
except ImportError:
    ON_JETSON = False

PORT_LEFT  = "COM3"
PORT_RIGHT = "COM10"
BAUDRATE   = 3000000

DIST_DANGER = 0.5
DIST_WARN   = 1.0

PIN_LEFT_WARN, PIN_LEFT_DANGER = 17, 27
PIN_RIGHT_WARN, PIN_RIGHT_DANGER = 22, 23

ST_WAITING = "연결 대기중"
ST_ERROR   = "연결 실패"
ST_OK      = "정상"

_lock = threading.Lock()

lidar_data = {
    "left":  {"angles": [], "distances": [], "min_dist": None, "status": ST_WAITING, "port": PORT_LEFT},
    "right": {"angles": [], "distances": [], "min_dist": None, "status": ST_WAITING, "port": PORT_RIGHT},
    "running": False
}

def _set(side, field, value):
    with _lock:
        lidar_data[side][field] = value

def get_snapshot() -> dict:
    with _lock:
        return {"left": dict(lidar_data["left"]), "right": dict(lidar_data["right"])}

def is_running() -> bool:
    with _lock: return lidar_data["running"]

def _setup_gpio():
    if not ON_JETSON: return
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    for pin in [PIN_LEFT_WARN, PIN_LEFT_DANGER, PIN_RIGHT_WARN, PIN_RIGHT_DANGER]:
        GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)

def _update_leds(side: str, min_dist_m):
    if not ON_JETSON or min_dist_m is None: return
    w_pin = PIN_LEFT_WARN if side == "left" else PIN_RIGHT_WARN
    d_pin = PIN_LEFT_DANGER if side == "left" else PIN_RIGHT_DANGER
    GPIO.output(w_pin, GPIO.HIGH if 0 < min_dist_m <= DIST_WARN else GPIO.LOW)
    GPIO.output(d_pin, GPIO.HIGH if 0 < min_dist_m <= DIST_DANGER else GPIO.LOW)

def _parse_frame(ser, side: str) -> bool:
    for _ in range(2048):
        b = ser.read(1)
        if not b: return False
        if b[0] == 0x5A:
            b2 = ser.read(1)
            if b2 and b2[0] == 0x77:
                b3 = ser.read(1)
                if b3 and b3[0] == 0xFF: break
    else: return False

    lb = ser.read(2)
    if len(lb) < 2: return False
    plen = lb[0] | (lb[1] << 8)
    if plen == 0 or plen > 4096: return False
    
    payload = ser.read(plen)
    cs_byte = ser.read(1)
    if len(payload) != plen or not cs_byte: return False

    dist_data = payload[5:]
    num_pts = len(dist_data) // 2
    min_d = 9999.0

    for i in range(num_pts):
        idx = i * 2
        dist_mm = dist_data[idx] | (dist_data[idx + 1] << 8)
        if 0 < dist_mm < 16000:
            dist_m = dist_mm / 1000.0
            if dist_m < min_d: min_d = dist_m

    final_min = min_d if min_d < 9999.0 else None
    
    _set(side, "min_dist", final_min)
    _set(side, "status", ST_OK)
    _update_leds(side, final_min)
    return True

def _worker(port: str, side: str, log_callback=None):
    if port is None:
        _set(side, "status", ST_ERROR)
        if log_callback: log_callback(f"ℹ️ [LiDAR] {side.upper()} 포트가 None으로 설정됨 (비활성화)", "WARN")
        return

    _set(side, "status", ST_WAITING)
    
    # ⭐ 터미널에 접속 시도를 명확하게 출력! (사용자가 볼 수 있도록)
    if log_callback: log_callback(f"[LiDAR] {side.upper()} 포트({port}) 접속 확인 중...", "INFO")

    ser = None
    for attempt in range(1, 4):
        try:
            ser = serial.Serial(port, BAUDRATE, timeout=1)
            # ⭐ 1번에 성공했을 때도 터미널에 성공했다고 띄우도록 로그 추가
            if log_callback: log_callback(f"✅ [LiDAR] {side.upper()} 포트({port}) 연결 성공!", "INFO")
            break
        except Exception as e:
            if log_callback: log_callback(f"⚠️ [LiDAR] {side.upper()} 연결 시도 {attempt}/3 실패...", "WARN")
            time.sleep(1.0)
    
    if ser is None or not ser.is_open:
        if log_callback: log_callback(f"❌ [LiDAR] {side.upper()} 3회 연결 실패! (오류 확정)", "ERROR")
        _set(side, "status", ST_ERROR)
        return

    try:
        ser.reset_input_buffer()
        ser.write(bytes([0x5A, 0x77, 0xFF, 0x02, 0x00, 0x01, 0x00, 0x03]))
        
        while is_running():
            if not _parse_frame(ser, side):
                time.sleep(0.01)

        ser.close()
        _set(side, "status", ST_ERROR)
        _set(side, "min_dist", None)

    except Exception:
        if ser and ser.is_open: ser.close()
        _set(side, "status", ST_ERROR)
        _set(side, "min_dist", None)

def start(log_callback=None):
    if not SERIAL_AVAILABLE: return False
    _setup_gpio()
    with _lock: lidar_data["running"] = True
    threading.Thread(target=_worker, args=(PORT_LEFT, "left", log_callback), daemon=True).start()
    threading.Thread(target=_worker, args=(PORT_RIGHT, "right", log_callback), daemon=True).start()
    return True

def stop():
    with _lock: lidar_data["running"] = False
    if ON_JETSON: GPIO.cleanup()