# `safety_monitor.py`

Pi의 안전 필수 프로세스입니다. 센서, 전도 FSM, 버튼, 현장 경보, 알림, 배터리, NTRIP, CSV와 UI 상태 송신을 통합합니다.

```bash
python safety_monitor.py
python safety_monitor.py --sim --scenario tipover_front
python safety_monitor.py --calibrate
python safety_monitor.py --tag normal_walk
python safety_monitor.py --no-ui-link
```

센서 초기 점검 실패 후에도 백그라운드 재연결을 계속합니다. 각 센서의 `start()`는 반복 호출에 안전해야 합니다. 주 루프는 100 Hz로 IMU 원속도 기록을 유지하고, UI 상태는 낮은 주기로 전송합니다.

안전 원칙:

- UI 또는 Jetson 장애가 프로세스를 중단시키지 않는다.
- IMU 고장은 전도 판정 불가 상태로 경고한다.
- LiDAR 링크 단절 시 장애물 경고만 비활성화하고 전도 감지는 유지한다.
- 종료 시 모든 스레드·소켓·로그를 정리한다.
