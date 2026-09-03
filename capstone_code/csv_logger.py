"""
CSV 로거 — rosbag 대체.

계획서 §6.2의 "전도 임계값 실험 데이터 수집"에 필요하다.
현재 IMPACT_THRESHOLD_G = 2.8 이라는 숫자에는 아무 근거가 없다.
이 로거로 시나리오별 데이터를 모으고 tools/analyze_logs.py 로 분석해야
그 숫자를 방어할 수 있다. (심사에서 반드시 질문받는 지점)

실험 방법
    python safety_monitor.py --tag curb          # 보도블록 턱 넘기
    python safety_monitor.py --tag sudden_stop   # 급정지
    python safety_monitor.py --tag place_down      # 보행기 내려놓기
    python safety_monitor.py --tag car_load      # 차량 적재
    python safety_monitor.py --tag tipover_front  # (더미) 전방 전복
    python safety_monitor.py --tag tipover_side     # (더미) 측방 전복

    ⚠ 실제 고령자를 대상으로 전도를 재현하지 말 것.
      더미(모래주머니/마네킹) 또는 매트 위 젊은 피험자로 대체한다.
"""
import csv
import pathlib
import threading
import time

import config

HEADER = ["t", "roll_deg", "pitch_deg", "tilt_deg", "accel_g", "gyro_dps",
          "tipover_state", "left_m", "right_m", "fix_quality", "satellites"]


class SampleLogger:
    def __init__(self, tag: str = "session"):
        self.enabled = config.CSV_ENABLED
        self._lock = threading.Lock()
        self._n = 0
        self._f = None
        self._w = None
        if not self.enabled:
            return
        d = pathlib.Path(config.LOG_DIR)
        d.mkdir(parents=True, exist_ok=True)
        self.path = d / f"{tag}_{time.strftime('%Y%m%d_%H%M%S')}.csv"
        self._f = open(self.path, "w", newline="", encoding="utf-8")
        self._w = csv.writer(self._f)
        self._w.writerow(HEADER)

    def write(self, imu, obstacle, gps, tipover_state):
        if not self.enabled or self._w is None:
            return
        with self._lock:
            self._w.writerow([
                f"{imu.t_capture:.3f}",
                f"{imu.roll_deg:.2f}", f"{imu.pitch_deg:.2f}",
                f"{imu.tilt_deg:.2f}", f"{imu.accel_g:.4f}",
                f"{imu.gyro_dps:.2f}",
                tipover_state,
                "" if obstacle.left_m is None else f"{obstacle.left_m:.3f}",
                "" if obstacle.right_m is None else f"{obstacle.right_m:.3f}",
                gps.fix_quality, gps.satellites,
            ])
            self._n += 1
            # 전원이 갑자기 끊겨도 최근 2초까지는 남도록 주기적으로 flush
            if self._n % config.CSV_FLUSH_EVERY == 0:
                self._f.flush()

    def close(self):
        if self._f:
            try:
                self._f.flush()
                self._f.close()
            except Exception:
                pass
