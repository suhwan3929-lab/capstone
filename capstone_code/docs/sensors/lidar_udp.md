# `sensors/lidar_udp.py`

> **한 줄:** Jetson의 ROS 2 브리지 노드에서 UDP로 장애물 거리를 받는다. (실기 구성)
> **계층:** 센서 수신 | **의존:** `config`, `schema`

---

## 설계 원칙 3가지

### 1. 비신뢰 UDP가 정답이다

장애물 거리는 "최신값만 의미 있음" 성격이므로 재전송이 오히려 해롭다.
계획서 §3.3에서 이 토픽을 `BEST_EFFORT` 로 정한 것과 같은 판단이다.

### 2. 데이터가 없어도 매 주기 보낸다

패킷 자체가 하트비트다.
→ **"감지된 물체 없음"과 "링크 끊김"을 수신 측이 구분할 수 있다.**

### 3. 신선도는 수신 측 도착 시각으로 판정한다

송신 타임스탬프는 진단용(`latency_s`)으로만 쓴다.
→ **두 보드의 시계 동기화(chrony)에 의존하지 않는다.** chrony가 어긋나도 오동작하지 않는다.

## 공개 인터페이스

```python
snapshot() -> ObstacleReport     # link_ok=False면 거리값은 전부 None
status(side) -> str
start(log_callback); stop()
run_integrity_check(log_callback)  # 3초 안에 패킷이 오는가
```

## 패킷 스키마 (UDP 9100)

```json
{"v": 1, "seq": 1234, "t": 1755766000.123,
 "left":  {"d": 1.42, "ok": true},
 "right": {"d": null, "ok": true},
 "curb_m": 0.9, "curb_type": "drop"}
```

`curb_*` 는 `.get()` 으로 읽어 **구버전 브리지와도 호환**된다.

## 고칠 때 주의

- ⚠ **링크가 끊기면 낡은 거리값을 절대 내보내지 않는다.** 이 규칙을 깨면
  화면과 부저가 존재하지 않는 장애물을 계속 경고한다.
- ⚠ **seq 역전은 버리되 재시작은 수용한다.**
  ```python
  if new <= prev and (prev - new) < 1000: continue
  ```
  이 예외가 없으면 **Jetson 재부팅 후 모든 패킷을 영구히 거부한다.**
- 수신 루프는 깨진 패킷 하나로 죽지 않도록 예외를 삼킨다.

## 테스트

`tests/test_components.py::test_lidar_udp_rejects_stale_and_accepts_restart`,
`test_lidar_link_loss_hides_stale_distance`
