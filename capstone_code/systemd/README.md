# systemd 설치 (Pi 5)

<!-- project-status:2026-10-12:start -->
> 갱신: 2026-10-12 · [진행 현황·확인 범위](../docs/progress_2026-10-12.md)
> 실행·Ubuntu 원격접속·Git 배포의 최신 진행 기록을 연결했다. 기존 날짜별 검토·시험 결과와 아직 미확인인 실기 항목을 구분한다.
<!-- project-status:2026-10-12:end -->

프로세스를 분리하는 목적은 성능이 아니라 **격리**다.
GUI가 멈춰도 전도 감지는 계속 동작해야 한다.

## 적용 전 경로·계정 확인

이 문서와 기존 유닛은 코드가 `/opt/walker`에 직접 설치된 템플릿이다.
Pi의 후속 기록은 `/opt/walker/capstone_code`, GUI 사용자는 `yu`이므로 그대로 등록하지 않는다.
실제 WorkingDirectory/ExecStart, walker 서비스 계정과 시리얼/GPIO 권한, 로그 쓰기 권한,
GUI 로그인 세션의 DISPLAY·인증 접근을 먼저 맞춘다. DISPLAY=:0만으로 접근을 보장하지 않는다.
`gpio` 그룹 존재 여부도 Ubuntu에서 확인한다.

수동 normal_walk와 실센서 실행을 확인한 뒤 아래 배포 템플릿을 적용한다.
현재 서비스 자동 시작·재부팅·UI 격리 성공을 새로 확인한 기록은 없다.

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
