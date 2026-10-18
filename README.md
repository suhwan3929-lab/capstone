# 고령자 보행기 안전 보조 시스템

<!-- project-status:2026-10-12:start -->
> 갱신: 2026-10-18 · [진행 정리·확인 범위](capstone_code/docs/progress_2026-10-18.md)
> 실행·Ubuntu 원격접속·Git 배포의 최신 진행 기록을 연결했다. 기존 날짜별 검토·시험 결과와 아직 미확인인 실기 항목을 구분한다.
<!-- project-status:2026-10-12:end -->

Jetson은 ROS 2 LiDAR 처리, Raspberry Pi는 Python 안전 감시와 대시보드를 담당한다.

- [현재 진행 정리와 미확인 항목](capstone_code/docs/progress_2026-10-18.md)
- [소프트웨어 구조·기본 실행](capstone_code/README.md)
- [Ubuntu SSH·APT 잠금 해결](capstone_code/docs/remote_access.md)
- [Git 업데이트와 코드 버전 확인](capstone_code/docs/git_update.md)
- [단계별 최종 시험](최종%20테스트.md)

현재 배포 브랜치와 작업 원본의 후속 기능은 같지 않다. GitHub 최신 여부와 실제 장치 적용 여부를 각각 확인한다.

이번 진행 정리에는 Discord 시험·자동 실행·유선 LAN 준비를 포함한다. 상위 작업 원본에만 있는 후속 코드와 장치 적용은 보고서에서 구분한다.

**현재 게시 기준은 main이다.** 2026-10-18 사용자 요청에 따라 기존 작업 브랜치의 변경을 main으로 반영한다. 과거 브랜치 기록과 소스/장치 적용 범위는 [Git 배포 안내](capstone_code/docs/git_update.md)를 따른다.

main은 PR과 쓰기 권한 리뷰어 1명의 승인이 필요하다. [반영 대기 PR #1](https://github.com/suhwan3929-lab/capstone/pull/1)은 테스트 43개를 통과했으며 현재 승인 대기다. 직접 push와 병합 시도는 보호 규칙으로 거부돼 아직 원격 main에는 반영되지 않았다.
