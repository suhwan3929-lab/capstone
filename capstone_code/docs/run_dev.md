# `run_dev.py`

<!-- project-status:2026-10-12:start -->
> 갱신: 2026-10-12 · [진행 현황·확인 범위](progress_2026-10-12.md)
> Ubuntu SSH·APT 잠금·GUI 없는 실행 조건을 반영했다. 절차 안내와 장치 접속/실행 성공 기록을 구분한다.
<!-- project-status:2026-10-12:end -->

> **한 줄:** 개발 PC에서 `safety_monitor` 와 `ui` 를 함께 띄우는 편의 실행기.
> **계층:** 개발 도구 | **실행:** `python run_dev.py`

---

## 무엇을 하는가

두 프로세스를 `subprocess` 로 띄우고 출력을 접두사와 함께 한 터미널에 합쳐 보여준다.

```bash
python run_dev.py                                    # 실제 센서
python run_dev.py --sim --scenario tipover_front     # 시뮬레이터
python run_dev.py --tag curb                         # CSV 태그 전달
python run_dev.py --no-ui                            # 모니터만
```

## 왜 존재하는가

실기(Pi)에서는 systemd가 이 역할을 한다. 이 스크립트는 **개발 PC에서 터미널 2개를
띄우는 번거로움만 없애주는 물건**이며, **두 프로세스가 분리되어 있다는 사실은 그대로다.**

즉 이것은 편의 도구이지 아키텍처가 아니다.

## 동작

- `safety_monitor` → `ui` 순으로 1.5초 간격을 두고 띄운다 (UDP 수신 준비 여유)
- 각 프로세스의 stdout을 별도 스레드가 읽어 `[모니터]` / `[  UI  ]` 접두사를 붙인다
- **모니터가 죽으면 전체 종료**, UI가 죽으면 모니터만 계속 (격리 원칙 반영)
- `Ctrl+C` 시 `terminate()` → 0.5초 후 `kill()`

## 고칠 때 주의

- ⚠ **이 스크립트에 로직을 넣지 말 것.** 여기서만 동작하고 실기에서는 안 되는
  기능이 생기면 안 된다. systemd는 이 파일을 쓰지 않는다.
- 새 CLI 옵션을 `safety_monitor.py` 에 추가하면 여기 `extra` 리스트에도 전달을 추가해야 한다.

## Ubuntu Pi 첫 실행과 SSH

run_dev.py는 Pi에서도 수동 첫 실행에 사용할 수 있다. 자동 시작 서비스 등록 완료를 뜻하지 않는다.
동일한 가상환경에서 정상 보행으로 기본 실행을 확인한다.

```bash
python run_dev.py --sim --scenario normal_walk --no-alert
python run_dev.py --sim --scenario normal_walk --no-alert --no-ui
```

첫 줄은 로그인된 Pi/RDP 데스크톱, 둘째 줄은 GUI 없는 SSH에서 사용한다.
두 줄을 동시에 실행하지 않는다. 종료는 Ctrl+C다.
`--no-alert`는 경보 출력을 끄며 알림 통신 전체를 차단하지 않는다.
[SSH 준비](remote_access.md)와 [Git 업데이트](git_update.md)를 먼저 확인한다.
