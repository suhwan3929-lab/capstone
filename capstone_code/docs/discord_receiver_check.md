# Pi에서 기존 Discord 봇의 수신 시험

별도 PuTTY 창에서 실행한다. 현재 --no-notify로 실행 중인 안전감시 시험은 유지할 수 있다.
전송 도구는 별도 프로세스이며 알림 워커를 시작하거나 기존 전송 대기 기록을 읽지 않는다.

```bash
git -C "$HOME/capstone" pull --ff-only origin main
cd "$HOME/capstone/capstone_code"
/opt/walker/venv/bin/python tools/discord_test.py --send --prompt
```

시험용 텍스트 채널 ID와 기존 봇 토큰을 입력한다. 토큰에는 `Bot ` 접두사를 붙이지 않는다.
토큰은 화면에 표시하거나 파일에 저장하지 않으며 이번 실행에서만 사용한다.
숨김 입력을 지원하지 않는 환경에서는 평문 입력으로 전환하지 않고 중단한다.
토큰이나 웹훅 URL을 채팅, 스크린샷 또는 Git에 포함하지 않는다.

보내는 문구는 `🧪 [연결 시험] 보행기 Discord 신고 연결 확인 — 실제 사고가 아닙니다.`다.
사용자가 고른 채널에 전송하며 멘션을 발생시키지 않고 GPS 좌표를 첨부하지 않는다.

터미널 전송 성공과 실제 채널에 도착한 것은 구분한다. 채널에서 문구를 확인해야 수신 시험을 완료한 것으로 본다.
실패하면 비밀값을 제외한 HTTP 상태와 출력만 확인한다. 401은 토큰, 403은 채널 접근/메시지 권한 등을 확인한다.
이 시험은 봇 설정을 영구 저장하거나 기존 안전감시의 --no-notify를 해제하지 않는다.
성공 후 보호된 장치 설정 저장, GUI SOS 경로, 자동 실행 등록과 재부팅을 차례로 진행한다.

참고: [채널 ID 확인](https://support.discord.com/hc/en-us/articles/206346498-Where-can-I-find-my-User-Server-Message-ID),
[메시지 전송 API](https://docs.discord.com/developers/resources/message#create-message).
