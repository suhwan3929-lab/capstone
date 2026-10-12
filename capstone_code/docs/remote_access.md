# Ubuntu Pi 원격 명령 입력과 SSH 설치

<!-- project-status:2026-10-12:start -->
> 갱신: 2026-10-12 · [진행 현황·확인 범위](progress_2026-10-12.md)
> Ubuntu SSH·APT 잠금·GUI 없는 실행 조건을 반영했다. 절차 안내와 장치 접속/실행 성공 기록을 구분한다.
<!-- project-status:2026-10-12:end -->

Windows PC는 유선 LAN, Pi는 Wi-Fi여도 같은 공유기에서 서로 통신할 수 있으면 접속한다.
게스트 Wi-Fi의 장치 격리나 별도 VLAN은 추가 확인한다. Raspberry Pi OS 전용
`raspi-config`와 Raspberry Pi Connect 설치 절차를 Ubuntu에 그대로 적용하지 않는다.
RealVNC 체험판 만료는 Ubuntu의 OpenSSH 설치·사용과 별개다.

## Pi의 Ubuntu 터미널에서 SSH 설치

처음에는 Pi의 모니터·키보드로 터미널을 연다. 이미 접속 가능한 다른 경로가 있으면 사용해도 된다.

```bash
sudo apt update
sudo apt install -y openssh-server
sudo systemctl enable --now ssh
systemctl status ssh --no-pager
sudo ss -ltnp 'sport = :22'
hostname -I
whoami
```

설치 성공, 서비스 또는 SSH 소켓의 TCP 22 LISTEN, 실제 IP와 사용자명을 확인한다.
Ubuntu 버전에 따라 SSH 소켓 활성화를 사용할 수 있으므로 서비스 표시만으로 판정하지 않는다.

## Windows PowerShell에서 접속

이 대화에서 사용한 주소와 계정은 다음과 같다. IP는 DHCP로 바뀔 수 있어 매번 현재 주소를 확인한다.

```powershell
ssh yu@192.168.0.173
```

처음 접속할 때 대상 장치의 호스트 키를 확인한 뒤 승인한다. 비밀번호는 Pi의 Ubuntu 계정 비밀번호다.
입력 중 문자가 표시되지 않는 것은 정상이다. 비밀번호를 문서·채팅·Git에 저장하지 않는다.

`Connection refused`는 해당 주소/포트에서 연결을 거부한 결과다. SSH 미설치·미실행,
다른 장치의 IP, 포트 변경 또는 방화벽의 명시적 거부를 구분한다. 비밀번호 인증 이전 단계다.
시간 초과라면 IP, 공유기 접근 경로, Wi-Fi 격리와 방화벽을 확인한다.

UFW가 활성 상태이고 SSH 허용 규칙이 없을 때만 PC의 실제 주소로 범위를 제한해 허용한다.
아래 `WINDOWS_PC_IP`는 Windows의 `ipconfig`에서 확인한 주소로 바꾼다.

```bash
sudo ufw status
sudo ufw allow from WINDOWS_PC_IP to any port 22 proto tcp
```

## waiting for cache lock

이 대화의 사진에서는 `unattended-upgrade` 프로세스 13069가 `/var/lib/dpkg/lock-frontend`를
보유했고 OpenSSH 설치 명령이 대기했다. 13069는 당시 번호이며 이후에 재사용할 고정 번호가 아니다.
여러 `sudo`/`apt` 행이 보인다고 여러 설치가 동시에 실행된다고 단정하지 않는다.

Pi에서 새 터미널을 열어 확인한다.

```bash
pgrep -a -f 'apt|dpkg|unattended'
sudo tail -n 20 /var/log/unattended-upgrades/unattended-upgrades.log
sudo tail -n 10 /var/log/dpkg.log
```

최근 기록의 시간과 패키지가 계속 바뀌는지 확인하고 진행 중이면 완료를 기다린다.
5~10분은 첫 점검 간격이며 강제 종료 기준이나 완료 시간 보장이 아니다.
오래 멈춰 있으면 해당 프로세스와 로그를 더 확인한다.
잠금 파일 삭제나 APT/dpkg의 임의 강제 종료는 설치 상태를 손상시킬 수 있다.
기다리던 설치가 정상 완료됐는지 확인한 뒤 SSH 시작과 접속을 재시도한다.

이 대화에는 후속 로그와 SSH 재접속 성공 결과가 아직 제출되지 않았다.
후속 문서의 다른 날짜 실기 기록과 이 오류의 해결 판정을 혼동하지 않는다.

## GUI 실행과의 차이

SSH는 터미널 접속이다. 일반 SSH 창에서 `ui.py`의 Tk 창이 Windows에 자동으로 나타나지는 않는다.
화면 없는 실행은 `run_dev.py --no-ui`를 사용한다. GUI는 Pi의 로그인된 데스크톱이나 구성한 RDP 세션에서 실행한다.
Ubuntu 내장 RDP, xrdp, VNC는 서버·포트·계정·세션 조건이 각각 다르다.

## 근거

- [Ubuntu OpenSSH 서버](https://ubuntu.com/server/docs/how-to/security/openssh-server/)
- [Ubuntu 자동 업데이트](https://documentation.ubuntu.com/server/how-to/software/automatic-updates/)
- [dpkg 잠금 파일 처리 원칙](https://wiki.debian.org/Teams/Dpkg/FAQ#db-lock)
