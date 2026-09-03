# systemd 설치 (Pi 5)

프로세스를 분리하는 목적은 성능이 아니라 **격리**다.
GUI가 멈춰도 전도 감지는 계속 동작해야 한다.

## 설치

```bash
sudo useradd -r -s /bin/false -G dialout,gpio walker || true
sudo install -d -o walker -g walker /opt/walker /var/log/walker
sudo rsync -a --exclude legacy --exclude logs ./ /opt/walker/

python3 -m venv /opt/walker/venv
/opt/walker/venv/bin/pip install -r /opt/walker/requirements.txt
```

`dialout` 그룹이 없으면 시리얼 포트를 열 수 없다.

## 비밀값

```bash
sudo install -d -m 700 /etc/walker
sudo tee /etc/walker/secrets.env >/dev/null <<'EOF'
WALKER_WEBHOOK_URL=https://discord.com/api/webhooks/...
NTRIP_USER=...
NTRIP_PASS=...
EOF
sudo chmod 600 /etc/walker/secrets.env
```

**이 파일을 git에 넣지 말 것.** 유출되면 제3자가 고령자의 실시간 위치를
수신하거나 위장 알림을 보낼 수 있다. (계획서 리뷰 §4.1)

## 등록

```bash
sudo cp systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now walker-safety
sudo systemctl enable --now walker-ui
```

## 확인

```bash
systemctl status walker-safety
journalctl -u walker-safety -f
tail -f /var/log/walker/fall.log
```

## 격리 검증 (반드시 해볼 것)

```bash
sudo systemctl stop walker-ui        # UI를 죽인다
journalctl -u walker-safety -f         # fall은 아무 일 없이 계속 도는가?
```

이게 확인되어야 "Jetson이 죽어도 Pi 단독으로 전도 알림은 살아 있어야 한다"는
계획서 요구사항이 실제로 지켜진 것이다.

## ROS 2 이행 시

이 3개 유닛이 launch 파일의
`Node(..., respawn=True, respawn_delay=2.0)` 3줄로 대체된다.
프로세스 경계를 지금 정해두면 그때 그대로 옮겨진다.
