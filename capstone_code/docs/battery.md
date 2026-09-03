# `battery.py`

> **한 줄:** 배터리 잔량 측정과 저전압 안전 종료.
> **계층:** 부가 | **의존:** `config`, `smbus2`(선택)

---

## 왜 존재하는가

리팩터링 전 코드는 `/sys/class/power_supply/BAT0` 를 읽었는데
**Raspberry Pi 5에는 BAT0가 없다.** 그래서 항상 100%를 반환했고,
화면에는 언제나 초록색 만충 표시가 떴다.

**틀린 계기판은 없는 계기판보다 나쁘다.** 실제로 5% 남았는데 100%로 보이면
시연 도중 전원이 나가도 원인을 못 찾는다.

또한 Jetson/Pi를 전원 차단으로 그냥 끄면 파일시스템이 깨진다.
잔량이 바닥나기 전에 **정상 종료**시키는 것이 SSD/SD 카드를 지키는 유일한 방법이다.

## 공개 인터페이스

```python
start(log_callback) -> bool     # 측정 수단이 있으면 True
stop()
snapshot() -> dict              # {percent, volts, current_a, charging, backend, t}
percent() -> float | None       # None = 측정 불가
volts_to_percent(v_pack, cells) # 리튬 전압 → 잔량 근사
```

**`percent()` 가 `None` 을 반환하는 것이 정상 동작이다.**
UI는 이때 "배터리 측정 안 됨"을 표시한다. 100%로 위장하지 않는다.

## 백엔드

| 이름 | 방식 | 비고 |
| :--- | :--- | :--- |
| `ina219` | I²C 전압+전류 | 전류 부호로 충방전 구분. **권장** |
| `max17043` | I²C 쿨롱 카운팅 | 1셀 기준이라 분압 필요 |
| `sysfs` | `/sys/class/power_supply/BAT0` | 노트북 등 실제 BAT0가 있는 환경 |
| `null` | 없음 | `percent()` → `None` |

## 경고 단계

| 잔량 | 동작 |
| ---: | :--- |
| ≤ `BATTERY_WARN_PCT` (20%) | 충전 필요 로그 |
| ≤ `BATTERY_CRITICAL_PCT` (10%) | 곧 종료됨 경고 |
| ≤ `BATTERY_SHUTDOWN_PCT` (5%) | **`sudo shutdown -h +1`** (`BATTERY_SHUTDOWN_ENABLED` 가 True일 때) |

## 고칠 때 주의

- ⚠ **`BATTERY_SHUTDOWN_ENABLED` 기본값은 False다.** 개발 중 PC가 꺼지면 곤란하므로.
  실기 배포 시 True로 바꿀 것.
- ⚠ **전압-잔량 곡선은 근사치다.** 부하 시 전압 강하 때문에 실제보다 낮게 나온다.
  정확한 잔량이 필요하면 쿨롱 카운팅(MAX17043)을 써야 한다.
- 측정 실패 시 예외를 삼키고 `percent=None` 으로 떨어뜨린다. 감시 스레드가 죽으면 안 되기 때문.

## 안전 (하드웨어)

⚠ 자작 리튬팩에는 **BMS(과충전/과방전/과전류/셀 밸런싱)와 인라인 퓨즈가 필수**다.
고령자가 체중을 싣는 기구에 들어가는 배터리다. 계획서 리뷰 §5.4 참조.

## 미해결 (하드웨어 필요)

- I²C 연료 게이지 모듈이 아직 없다. 코드는 완성 상태.
- `BATTERY_CELLS` (3S/4S)를 실제 팩 구성에 맞출 것.
