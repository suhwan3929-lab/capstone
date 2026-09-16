# 보행기 안전 보조 시스템

Raspberry Pi 5가 전도 판정·UI·알림을 담당하고, Jetson Orin Nano가 듀얼 LiDAR를 처리해 UDP로 장애물 정보를 전달하는 캡스톤 프로젝트입니다.

## 현재 상태

- Windows 자동 테스트: 안전·구성요소 35개, ROS 2 패키지 구조 3개 통과
- Jetson `walker_lidar`: ROS 2 `ament_python` 패키징 완료
- Pi systemd 경로: `/opt/walker/capstone_code`로 통일
- 남은 핵심: 실제 보드 빌드, 센서 설정·교정, 실외 데이터 기반 임계값 확정

Windows 통과는 코드 구조와 시뮬레이션 검증이며 실제 센서 호환성을 보증하지 않습니다.

## 문서

| 목적 | 문서 |
| --- | --- |
| Pi·Jetson 설치 | [작업_목록.md](작업_목록.md) |
| 남은 실기 작업 | [할일_목록.md](할일_목록.md) |
| 실행·테스트 | [capstone_code/README.md](capstone_code/README.md) |
| 현재 코드 검토 | [코드_리뷰.md](코드_리뷰.md) |
| 설계값 근거 | [설계값_근거.md](설계값_근거.md) |
| 부품 영향 | [부품_변경_영향분석.md](부품_변경_영향분석.md) |
| 감지 거리 | [감지거리_타당성.md](감지거리_타당성.md) |

## 구성

```text
capstone_code/       Pi 애플리케이션과 테스트
capstone_code/jetson Jetson ROS 2 LiDAR 패키지
capstone_code/systemd Pi 자동 실행 서비스
```

비밀값은 커밋하지 않고 `config_local.py` 또는 systemd 환경 파일로 관리합니다.
