# 기존 웹훅 고정 및 실제 Pi GPS 지도 수신 시험

2026-11-06 사용자 Discord 사진과 '제대로 나왔어' 보고로 기존 웹훅의 비사고 연결 시험 문구 수신을 확인했다.
사용자는 같은 웹훅을 고정하고 지도를 함께 보내는 시험을 요청했다. 이 문서의 추가 설정/지도 발송은 별도 실행 결과가 필요하다.

## 1. 코드 업데이트 및 웹훅 저장

Pi의 새 PuTTY 창에서 실행한다. 기존 안전감시 시험은 아직 유지할 수 있다.

```bash
git -C "$HOME/capstone" pull --ff-only origin main
cd "$HOME/capstone/capstone_code"
sudo python3 tools/configure_webhook.py
```

기존 Discord 설정의 '웹훅 URL 복사'로 가져온 주소를 숨김 입력한다. 채팅으로 보내지 않는다.
`/etc/walker/secrets.env`에 `WALKER_NOTIFY_BACKEND=webhook`과 URL을 저장한다.
기존 다른 설정은 보존하며 기존 파일이 있으면 같은 디렉터리에 권한600 백업을 남긴다.
새 파일은 root 소유/권한600이다. 저장은 현재 프로세스나 서비스 시작 상태를 변경하지 않는다.
안전서비스의 기존 EnvironmentFile 설정은 이 경로를 사용한다. 수동 시험은 아래처럼 명시적으로 읽는다.

## 2. 지도 포함 시험

안전감시가 실행 중인 기존 PuTTY에서 Ctrl+C로 종료하고 '종료 완료'를 기다린다.
GPS 포트를 두 프로그램에서 동시에 열지 않도록 한다. GUI는 열어 두어도 된다.
안전감시를 멈춘 동안 GUI의 모니터 연결 끊김 표시는 예상되는 상태다.

새 PuTTY 창에서 실행한다.

```bash
cd "$HOME/capstone/capstone_code"
sudo /opt/walker/venv/bin/python tools/discord_test.py --send --secrets-file /etc/walker/secrets.env --gps-location --map-image
```

Pi 실제 GPS에서 새 위치를 최대15초 기다린다. 위치가 없거나 지도를 받지 못하면 메시지를 보내지 않는다.
전송 직전 위치는60초 이내에 수신된 값이어야 한다. 측정값의 장치 수신 UTC/GPS UTC와 경과 시간을 구분해 표시한다.
GPS 오차가 HDOP 수치와 같다고 주장하지 않는다.
기존 GUI와 같은 TileClient의 앱 식별정보/HTTP 캐시 처리를 사용하여 이미지에 필요한 타일만 받는다.
빨간 점은 GPS 측정 위치다. 저작자 표시와 지도 링크를 함께 첨부한다.
예전 별도 staticmap 서버 경로도 같은 지도 렌더러를 사용하도록 통일했다.

메시지는 `[GPS 지도 시험] 실제 사고가 아닙니다.`로 시작한다. 멘션과 기존 대기 알림 복원은 없다.
터미널 성공과 실제 채널의 이미지 도착을 각각 확인한다. 실제 위치 좌표가 해당 웹훅 채널에 공유되는 시험이다.
이 실행은 안전감시 자동 시작을 등록하거나 --no-notify 시험 프로세스를 운영 모드로 바꾸지 않는다.
지도 수신을 확인한 다음 GUI SOS 경로와 자동 실행을 진행한다.

설정 롤백은 root가 보호된 백업을 같은 권한으로 복원한다. 비밀 파일 내용을 cat하거나 채팅/Git에 붙이지 않는다.
