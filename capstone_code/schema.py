"""
메시지 스키마 — 모듈 사이를 오가는 모든 데이터의 형태를 여기서 못박는다.

규칙:
  * 즉석 dict를 만들어 넘기지 말 것. 반드시 여기 정의된 dataclass를 쓴다.
  * 변수명에 단위를 붙인다 (`accel_g`, `left_m`, `roll_deg`).
  * 모든 샘플은 수집 시각(`t_capture`)을 갖는다.

ROS 2 이행 시:
  이 파일이 그대로 `msg/` 디렉터리가 된다.
    ImuSample       → sensor_msgs/Imu        (accel_g × 9.80665 → m/s²)
    GpsFix          → sensor_msgs/NavSatFix  (+ 품질은 별도 토픽)
    ObstacleReport  → 커스텀 .msg 또는 sensor_msgs/LaserScan 요약
    SystemStatus    → 커스텀 .msg
  `t_capture`가 `header.stamp`가 되고, `valid` 플래그는 토픽 미발행으로 대체된다.

좌표계 규약(REP-103): x=전방, y=좌측, z=상방. 각도 단위는 deg.
"""
from dataclasses import dataclass, field, asdict
from typing import Optional

from states import CONN_WAITING


# ══════════════════════════════════════════════════════════
# 센서 샘플
# ══════════════════════════════════════════════════════════
@dataclass
class ImuSample:
    """EBIMU-9DOFV6 한 샘플. roll/pitch는 장착각 보정 후 값."""
    t_capture: float = 0.0
    roll_deg: float = 0.0
    pitch_deg: float = 0.0
    yaw_deg: float = 0.0
    accel_g: float = 0.0          # 가속도 벡터합 (정지 시 ≈ 1.0)
    gyro_dps: float = 0.0         # 각속도 벡터합
    status: str = CONN_WAITING
    valid: bool = False           # False면 값을 신뢰하지 말 것

    @property
    def tilt_deg(self) -> float:
        """수평면 기준 기울기. 전도 판정의 핵심 지표."""
        return max(abs(self.roll_deg), abs(self.pitch_deg))


@dataclass
class GpsFix:
    """ZED-F9P 측위 결과."""
    t_capture: float = 0.0
    lat: Optional[float] = None
    lon: Optional[float] = None
    alt_m: Optional[float] = None
    speed_kmh: Optional[float] = None
    fix_quality: int = 0          # 0=불가, 1=단독, 2=DGPS, 4=RTK고정, 5=RTK부동
    satellites: int = 0
    hdop: Optional[float] = None
    utc: Optional[str] = None     # 위성 UTC — 보드 RTC가 틀려도 신뢰 가능
    status: str = CONN_WAITING
    valid: bool = False

    @property
    def has_position(self) -> bool:
        return self.valid and self.lat is not None and self.lon is not None


@dataclass
class ObstacleReport:
    """좌/우 LiDAR의 전방 최근접 거리. None = 감지 없음."""
    t_capture: float = 0.0
    left_m: Optional[float] = None
    right_m: Optional[float] = None
    left_ok: bool = False         # 해당 센서가 살아 있는가
    right_ok: bool = False
    link_ok: bool = False         # (UDP 모드) Jetson과의 링크가 살아 있는가
    latency_s: Optional[float] = None   # 시계 동기 진단용
    #: 바닥 단차(턱)까지의 거리. 기획 배경의 "턱 걸림"에 대응한다.
    #: 전방을 수평으로 보는 LiDAR로는 볼 수 없어, Jetson에서 지면 평면을
    #: 추정한 뒤 그 평면에서 벗어난 편차로 계산한다.
    curb_m: Optional[float] = None
    curb_type: str = ""           # "" | "drop"(내려가는 턱) | "rise"(올라가는 턱)

    @property
    def nearest_m(self) -> Optional[float]:
        vals = [d for d in (self.left_m, self.right_m) if d is not None]
        return min(vals) if vals else None


# ══════════════════════════════════════════════════════════
# 프로세스 간 상태 패킷 (safety_monitor → ui)
# ══════════════════════════════════════════════════════════
@dataclass
class HealthReport:
    """부가 상태 — 배터리 / RTK 보정 / 알림 대기열."""
    battery_pct: Optional[float] = None    # None = 측정 수단 없음 (100%로 위장 금지)
    battery_volts: Optional[float] = None
    charging: bool = False
    battery_backend: str = ""
    ntrip_connected: bool = False
    ntrip_healthy: bool = False            # 보정정보가 실제로 흐르고 있는가
    ntrip_bytes: int = 0
    alerts_pending: int = 0                # 아직 보내지 못한 보호자 알림 수
    alert_backend: str = ""


@dataclass
class SystemStatus:
    seq: int = 0
    t: float = 0.0
    tipover_state: str = ""
    ask_deadline: Optional[float] = None   # 응답 대기 종료 시각 (카운트다운용)
    alert_sent: bool = False
    imu: ImuSample = field(default_factory=ImuSample)
    gps: GpsFix = field(default_factory=GpsFix)
    obstacle: ObstacleReport = field(default_factory=ObstacleReport)
    health: HealthReport = field(default_factory=HealthReport)
    notice: Optional[str] = None           # UI 터미널에 띄울 한 줄

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "SystemStatus":
        return SystemStatus(
            seq=d.get("seq", 0),
            t=d.get("t", 0.0),
            tipover_state=d.get("tipover_state", ""),
            ask_deadline=d.get("ask_deadline"),
            alert_sent=d.get("alert_sent", False),
            imu=ImuSample(**d.get("imu", {})),
            gps=GpsFix(**d.get("gps", {})),
            obstacle=ObstacleReport(**d.get("obstacle", {})),
            health=HealthReport(**d.get("health", {})),
            notice=d.get("notice"),
        )
