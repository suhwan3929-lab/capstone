# V6 송신기와 기존 USB 수신기의 Pi 연결 확인

2026-11-06 사용자 실행 결과를 기준으로 한다. 수신기는 기존 장치이며 송신기만 V6로 교체했다.
정확한 전체 모델명과 펌웨어는 아직 확인하지 않았다.

## 확인한 범위

- USB 수신기: CP2102N, `10c4:ea60`, 일련번호 `0001`.
- Pi의 기존 udev 규칙으로 `/dev/walker_imu -> ttyUSB0` 생성 확인.
- 921600bps에서 `100-0,0.10,0.29,-125.71,0.0,0.0,0.0,0.005,0.001,1.005` 형식 수신.
- 기존 main 드라이버는 무선 CH-ID 접두어를 처리하지 못한다. 무선 수신과 유선 수신을 명시적으로 선택하도록 수정한다.

현재 사진은 원본 수신 증거다. 수정 드라이버의 Pi 실행, 움직임 응답, 가속도 측정 범위,
최종 장착각 보정과 안전감시 통합은 각각 별도로 확인해야 한다.

제조사 자료: [EBMotion V6 매뉴얼](https://www.e2box.co.kr/m/entry/EBMotion-V6-매뉴얼).
USB 인식과 현재 프레임 수신만으로 모든 구형 수신기와 V6의 기능 호환을 보장하지 않는다.

## Pi에서 적용

다른 프로그램이 IMU 포트를 읽고 있다면 먼저 종료한다. 현재 GUI만 실행하는 상태는 유지할 수 있다.
Pi PuTTY에서 실행하며, `config_local.py`는 기존 GPS와 Ethernet 설정을 유지한다.

```bash
git -C "$HOME/capstone" pull --ff-only origin main
cd "$HOME/capstone/capstone_code"
cp -a config_local.py "config_local.py.before-imu-$(date +%Y%m%d-%H%M%S)"
cat >> config_local.py <<'PY'

IMU_PORT = "/dev/walker_imu"
IMU_BAUD = 921600
IMU_PROTOCOL = "wireless"
IMU_CHANNEL = 100
IMU_SENSOR_ID = 0
IMU_CONFIGURE_ON_CONNECT = False
PY
```

마지막 동일 이름 설정이 우선한다. 고정 이름은 기존 udev 규칙을 재사용한다.
위 설정은 출력 설정 명령을 보내지 않는다. 재연결 후에도 이 방식을 유지한다.
숫자 9개, 유한 값, 채널 100 / 센서 ID 0 및 완성된 줄만 사용한다.
출력 필드가 바뀌면 유효한 샘플로 처리하지 않으므로 원본부터 다시 확인한다.

기존 유선 설치의 기본값은 `wired` / 115200 / 설정 명령 사용으로 유지한다.
무선 설정 명령 사용은 기존 EBMotion 수신기 절차이며, 이번 V6 구성에는 적용하지 않는다.

## 드라이버 단독 확인

```bash
/opt/walker/venv/bin/python - <<'PY'
import config
from sensors import imu_sensor
print("IMU:", config.IMU_PORT, config.IMU_BAUD, config.IMU_PROTOCOL)
print("CONFIGURE_ON_CONNECT:", config.IMU_CONFIGURE_ON_CONNECT)
ok = imu_sensor.run_integrity_check(lambda msg, level: print(msg, flush=True))
print("IMU_DATA_OK" if ok else "IMU_DATA_FAIL")
PY
```

`CONFIGURE_ON_CONNECT: False`와 `IMU_DATA_OK`를 확인한다.
이 명령은 전체 안전감시, GUI 상태 전송, Discord 또는 SOS 알림을 시작하지 않는다.
실시간 움직임은 다음 단계에서 확인한다. 정지 시 약 1g만으로 측정 범위를 확정하지 않는다.

되돌리려면 방금 생성한 `config_local.py.before-imu-날짜` 파일을 `config_local.py`로 복원한다.
드라이버는 유선 모드도 지원하므로 코드 전체를 되돌릴 필요는 없다.
