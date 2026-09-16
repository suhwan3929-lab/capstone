# Pi systemd 설치

서비스는 코드가 `/opt/walker/capstone_code`, 가상환경이 `/opt/walker/venv`에 있다고 가정합니다.

```bash
sudo cp /opt/walker/capstone_code/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now walker-safety walker-ui
systemctl status walker-safety walker-ui
journalctl -u walker-safety -f
```

웹훅·NTRIP 비밀값은 `/etc/walker/secrets.env`에 두고 권한을 제한합니다.

```bash
sudo chown root:walker /etc/walker/secrets.env
sudo chmod 640 /etc/walker/secrets.env
```

검증:

1. UI 종료 후 `walker-safety`가 계속 동작하는지 확인
2. Jetson 전원 차단 후 전도 감지가 유지되는지 확인
3. 센서 분리·재연결과 서비스 자동 복구 확인
4. 재부팅 후 두 서비스 상태와 로그 확인

UI 서비스가 안전 서비스를 끌어내리지 않도록 두 서비스는 독립적으로 유지합니다.
