# Git 업데이트 판단과 배포 경로

<!-- project-status:2026-10-12:start -->
> 갱신: 2026-10-12 · [진행 현황·확인 범위](progress_2026-10-12.md)
> Windows 배포용 저장소의 편집 전 상태와 Pi의 별도 확인 절차를 기록했다. 문서 갱신 직후 상태를 기록하며, 이후 GitHub 게시 여부는 원격 커밋으로 확인한다.
<!-- project-status:2026-10-12:end -->

## 2026-10-12 문서 변경 직전 확인

Windows의 실제 배포용 Git 저장소는 `D:\26-1\26-2 capstone\.publish-capstone`이다.
상위 작업 폴더의 `capstone_code`와 이 저장소의 코드는 서로 다른 스냅샷이다.
상위 폴더에서 Git을 실행한 오류를 근거로 파일이 없거나 GitHub가 비었다고 판단하지 않는다.

- 원격: `https://github.com/suhwan3929-lab/capstone.git`
- 체크아웃: `codex/powerbank-discord-safety`, HEAD `bfb0372`
- 이 대화에서 `git fetch origin` 성공 후 현재 브랜치와 추적 브랜치 차이: 앞섬 0 / 뒤처짐 0.
- 문서 변경 직전 수정 파일: 없음. `main`과 `origin/main` 차이도 0 / 0으로 확인했다.
- 이 판정은 당시 로컬 브랜치가 자기 추적 브랜치와 같다는 뜻이다. 다른 브랜치의 최신 기능이나 Pi 설치 상태를 보장하지 않는다.

이번 문서 편집 후에는 로컬 `.md` 수정/추가 파일이 생긴다. 위의 깨끗한 상태는 편집 전 기록이다.
위 기록은 문서 갱신 직후, GitHub 게시 요청 전의 상태다. 이어진 사용자 요청으로 현재 배포 브랜치의 문서를 검증 후 커밋·푸시하는 절차를 진행한다. Pi에서의 pull과 적용은 별도다.

## Pi에서 pull이 필요한지 확인

Pi에서 실제 프로젝트의 Git 저장소 폴더로 이동한 뒤 실행한다.
ZIP 또는 파일 복사로 설치한 폴더는 `.git`이 없을 수 있으므로 먼저 확인한다.

```bash
git rev-parse --show-toplevel
git remote -v
git branch -vv
git fetch origin
git status -sb
git rev-list --left-right --count 'HEAD...@{upstream}'
```

마지막 명령의 왼쪽은 로컬만 가진 커밋, 오른쪽은 원격만 가진 커밋이다.
추적 브랜치가 없으면 해당 명령이 실패하므로 팀이 사용하는 원격·브랜치를 먼저 확인한다.

- `0 0`: 현재 추적 브랜치 기준 pull 불필요.
- `0 N` 또는 `behind N`: 원격에 새 커밋이 있다. 수정/추가 파일과 충돌 가능성을 확인한 뒤 업데이트한다.
- `N 0` 또는 `ahead N`: 로컬 커밋이 있으므로 pull만으로 처리할 문제가 아니다.
- 양쪽 모두 양수: 이력이 갈라져 있다. 자동 merge/rebase, reset, 브랜치 교체로 해결하지 않는다.

작업 내용을 확인해 안전한 상태일 때만 다음을 실행한다.

```bash
git pull --ff-only
```

fetch 실패·추적 브랜치 없음은 최신 여부 미확인이다. 로컬 수정과 `config_local.py`를 보존한다.
그냥 업데이트하려고 `git reset --hard`, `git clean`, 설정 파일 덮어쓰기를 사용하지 않는다.

## 소스가 달라 pull만으로 반영되지 않는 경우

상위 작업 폴더에는 무선 IMU, 사고 후 감시 재개, LiDAR 3D 표시 문서/소스가 있지만
현재 배포 브랜치에는 그 후속 파일 일부가 없다. 로컬 원본의 최신 기능이 GitHub에
게시되지 않았다면 Pi에서 pull해도 내려오지 않는다.
필요한 변경을 올바른 배포 저장소와 브랜치에 반영하고 검증·게시한 뒤 장치에서 받거나,
버전을 기록한 파일 배포 절차를 사용해야 한다. 이 문서 편집은 코드 동기화나 게시를 대신하지 않는다.

Pi의 프로그램은 업데이트 후 사용하는 실행 방식에 맞춰 재시작한다.
systemd가 설치되지 않은 상태에서 서비스 재시작을 완료했다고 기록하지 않는다.
Jetson ROS 2 Python 패키지가 바뀌었다면 해당 워크스페이스에서
`colcon build --packages-select walker_lidar`와 환경 source, 브리지 재시작이 별도로 필요하다.
실제 장치의 fetch/status 결과는 아직 이 대화에서 확인하지 않았다.
