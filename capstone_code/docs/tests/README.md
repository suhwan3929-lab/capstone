# 테스트

pytest 없이 실행할 수 있습니다.

```bash
python tests/run_all.py
python tests/run_all.py -v
python -m unittest discover -s jetson/test -p "test_*.py" -v
```

현재 구성:

- `test_tipover_fsm.py`: 전도 FSM 14개
- `test_components.py`: UDP·파서·경보·알림·배터리·배포·문법 21개
- `jetson/test/test_package_structure.py`: ROS 2 패키지 구조 3개

FSM은 가상 시계를 사용합니다. 네트워크 테스트는 고정 sleep 대신 조건을 기다립니다.

이 테스트는 Windows 코드 회귀와 패키지 구조를 검증합니다. ROS 2 빌드, 센서 포맷, GPIO, 실외 LiDAR 성능은 실제 Pi·Jetson에서 별도로 확인해야 합니다.
