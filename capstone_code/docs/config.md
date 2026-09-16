# `config.py`

공통 기본값을 정의하고, 존재하면 `config_local.py`의 장치별 값을 덮어씁니다. 비밀값과 포트·GPIO·보정값은 기본 파일에 넣지 않습니다.

주요 그룹:

- 센서 포트·baudrate·신선도 제한
- LiDAR 소스(`serial`, `udp`, `none`)와 UDP 주소
- 전도 임계값과 1~3초 자세창·75% 비율
- 움직임·응답·재무장 시간
- 경보, 배터리, 상태 링크, 시뮬레이터

설정 변경 후 `tests/run_all.py`와 실제 장치의 `config_local.py`를 함께 확인합니다. 전도 임계값은 실제 CSV와 `tools/replay.py --sweep` 결과 없이 확정하지 않습니다.
