# `csv_logger.py`

> **한 줄:** 실험 데이터를 100 Hz로 CSV에 기록한다. rosbag 대체.
> **계층:** 기록 | **의존:** `config`

---

## 왜 존재하는가

`IMPACT_THRESHOLD_G = 2.8` 이라는 숫자를 방어하려면 실측 데이터가 필요하다.
심사에서 "왜 2.8입니까?"를 반드시 묻는다.

이 로거가 남긴 CSV를 `tools/replay.py` 가 **실제 판정 코드에 다시 통과시켜**
임계값을 탐색한다.

## 공개 인터페이스

```python
class SampleLogger:
    def __init__(self, tag="session")            # logs/<tag>_<날짜시각>.csv
    def write(self, imu, obstacle, gps, tipover_state)
    def close(self)
```

## CSV 열

```
t, roll_deg, pitch_deg, tilt_deg, accel_g, gyro_dps,
tipover_state, left_m, right_m, fix_quality, satellites
```

## 설계 포인트

### 반드시 센서 원속도로 기록한다

**과거에 이 로거를 상태 표시 주기(10 Hz)에서 호출하는 버그가 있었다.**
강체 충돌의 가속도 전이는 수십 ms에 끝나므로 **10 Hz로는 충격 피크를 통째로 놓친다.**
`tools/replay.py` 를 만들어 돌려보고 나서야 드러난 문제다.

현재 `safety_monitor.py` 의 주 루프가 100 Hz로 돌며 매 새 샘플마다 호출한다.

### 주기적 flush

전원이 갑자기 끊겨도 최근 2초까지는 남도록 `CSV_FLUSH_EVERY` 마다 flush 한다.

## 실험 프로토콜

```bash
python safety_monitor.py --tag normal_walk
python safety_monitor.py --tag curb            # 보도블록 턱 넘기
python safety_monitor.py --tag sudden_stop
python safety_monitor.py --tag place_down      # 보행기 눕혀두기
python safety_monitor.py --tag car_load
python safety_monitor.py --tag tipover_front   # ← 더미/매트 사용
python safety_monitor.py --tag tipover_side
python safety_monitor.py --tag tipover_rear
```

**파일명 접두사가 곧 양성/음성 라벨이다.** `tipover_*` 가 양성,
`*_recover` 는 음성(해제되어야 함).

⚠ **실제 고령자를 대상으로 전도를 재현하지 말 것.**
더미(모래주머니·마네킹) 또는 매트 위 젊은 피험자로 대체한다.

## 고칠 때 주의

- ⚠ **열 순서를 바꾸거나 이름을 바꾸면 기존 로그와 호환이 깨진다.**
  `tools/replay.py` 는 `csv.DictReader` 로 이름 기준 접근하므로 순서 변경은 안전하지만,
  이름 변경은 파서도 같이 고쳐야 한다.
- `write()` 는 락을 잡는다. 100 Hz에서 부담이 되지는 않지만 안에서 무거운 일을 하지 말 것.
- 열을 추가하면 `HEADER` 와 `write()` 양쪽을 고칠 것.
