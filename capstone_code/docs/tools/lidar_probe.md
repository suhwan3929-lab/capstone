# `tools/lidar_probe.py`

> **한 줄:** LiDAR 프레임 포맷을 추측 대신 **측정**해서 확정한다.
> **계층:** 진단 도구 | **의존:** `config`, `pyserial`(dump 시)

---

## 해결하는 문제

`sensors/lidar_serial.py` 의 payload 오프셋과 비트 폭에는 **근거가 없다.**
CygLiDAR 3D 모드는 12비트 패킹일 가능성이 있고, 그 경우 파싱 결과는
**'그럴듯하지만 완전히 틀린' 값**이 된다.

**숫자가 그럴듯해서 틀린 줄을 모르는 것**이 이 문제의 위험한 점이다.

## 사용법 (권장 절차, 약 10분)

```bash
# 1) 평평한 판을 정면 1.0 m에 세우고 원시 바이트 수집
python tools/lidar_probe.py dump --port COM3 --seconds 5 --truth 1.00

# 2) 후보 레이아웃 전수 탐색
python tools/lidar_probe.py analyze logs/lidar_raw_COM3.bin --truth 1.00
```

3) 1순위로 나온 값을 `config_local.py` 에 적는다.

```python
LIDAR_PAYLOAD_OFFSET = 5
LIDAR_PACKING = "u12"
LIDAR_CHECKSUM = "xor"
```

**코드를 고칠 필요가 없다.**

## 탐색 범위

- 오프셋 **0~16** (기본)
- 패킹 **4종**: `u16le`, `u16be`, `u12`, `u12alt`
- 체크섬 **2종**: `xor`, `sum8` (프레임 60개로 일치율 확인)

## 점수 산정

| 요소 | 의미 | 가중치 |
| :--- | :--- | ---: |
| 유효 비율 | 값이 유효 거리 범위에 드는 비율 | 0.45 |
| 연속성 | 이웃 점이 1 m 이상 튀지 않는 비율 (실제 장면은 연속적) | 0.25 |
| **정답 근접** | 줄자로 잰 거리 ±12% 안에 몰리는 비율 | **0.60 (지배적)** |

`--truth` 를 주면 정답 근접이 지배적이 되어 판별 정확도가 크게 올라간다.

## 고칠 때 주의

- ⚠ **`dump` 는 하드웨어가 필요하다.** `analyze` 는 저장된 `.bin` 만 있으면 된다.
  한 사람이 덤프를 뜨면 나머지가 분석할 수 있다.
- 헤더를 못 찾으면 프로토콜 자체가 예상과 다른 것이다. 이때는
  **Cygbot 공식 ROS 2 드라이버 소스에서 파싱 규칙을 가져오는 것**이 정답이다.
- `iter_frames()` 는 가짜 헤더를 만나면 1바이트만 전진한다(롤링 버퍼).
  `lidar_serial.py` 와 같은 방식이다.

## 참고

실기에서는 **Jetson의 벤더 ROS 2 드라이버가 이 파싱을 대체한다.**
이 도구는 PC 개발용 `lidar_serial.py` 를 쓸 때 필요하다.
