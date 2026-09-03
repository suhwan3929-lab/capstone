# `status_link.py`

> **한 줄:** `safety_monitor` ↔ `ui` 프로세스 간 UDP 채널.
> **계층:** 통신 | **의존:** `config`, `schema`

---

## 왜 존재하는가

**성능이 아니라 격리** 때문이다. GUI가 멈추거나 죽어도 전도 감지가 영향을 받지 않아야 한다.
리팩터링 전에는 한 프로세스여서 tkinter가 멈추면 안전 기능도 같이 멈췄다.

```
safety_monitor ──상태 10 Hz──> ui        (UDP 9101)
ui ──사용자 응답──────────> safety_monitor  (UDP 9102)
```

## 공개 인터페이스

| 클래스 | 쪽 | 역할 |
| :--- | :--- | :--- |
| `StatusPublisher` | safety_monitor | `publish(SystemStatus)` — seq/타임스탬프 자동 부여 |
| `StatusSubscriber` | ui | `start()`, `latest()` → `(SystemStatus | None, alive)` |
| `CommandSender` | ui | `send(cmd)` — **3연발 전송** |
| `CommandListener` | safety_monitor | `start()` — 중복 제거 후 콜백 |

## 설계 포인트

### 명령은 3번 보낸다

사용자 취소는 놓치면 안 되는 명령이다. UDP 손실에 대비해 20 ms 간격으로 3번 보내고,
수신 측이 **0.5초 내 같은 명령은 중복으로 무시**한다.

### seq 역전 폐기 + 재시작 수용

```python
if seq <= prev_seq and (prev_seq - seq) < 1000:
    continue        # 순서 역전 → 폐기
# seq가 크게 뒤로 가면 송신 측 재시작 → 새 세션으로 수용
```

**이 예외가 없으면 송신 프로세스를 재시작한 뒤 모든 패킷을 영구히 거부한다.**

### UI가 없어도 죽지 않는다

`StatusPublisher.publish()` 는 `OSError` 를 삼킨다.
UI가 안 떠 있어도 `safety_monitor` 는 계속 동작해야 한다.

## 고칠 때 주의

- ⚠ **`SystemStatus` 에 필드를 추가하면 `schema.from_dict()` 도 같이 고칠 것.**
  안 고치면 조용히 기본값이 들어간다.
- ⚠ 수신 루프는 깨진 패킷 하나로 죽지 않도록 예외를 삼킨다.
  디버깅 중에는 이 `except` 를 잠시 풀어보는 편이 빠르다.
- 테스트에서는 포트를 인자로 넘겨 실제 포트와 충돌을 피한다(`port=19101` 등).

## ROS 2 이행 시

`StatusPublisher` → `/walker/status` 퍼블리셔,
`CommandListener` → `/walker/user_response` 서브스크라이버.

## 테스트

`tests/test_components.py::test_status_link_roundtrip`, `test_command_link_dedupes_burst`
