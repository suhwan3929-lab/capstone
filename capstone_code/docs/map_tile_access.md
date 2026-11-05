# GPS 지도 접근 차단 수정 및 Pi 적용

2026-11-06 사용자 화면에서 GPS DGPS/좌표/마커는 표시되지만 지도 배경은 OpenStreetMap 접근 차단 타일이었다.
기존 앱은 TkinterMapView 기본 네트워크 요청을 사용했다. 라이브러리 기본 식별정보와 주변 타일 사전 요청을 사용하지 않도록 수정한다.

## 요청 및 표시

- 공식 HTTPS URL `https://tile.openstreetmap.org/{z}/{x}/{y}.png`를 사용한다.
- 앱 식별정보 `CapstoneWalkerSafety/1.0 (+https://github.com/suhwan3929-lab/capstone)`를 보낸다. 브라우저나 다른 앱으로 위장하지 않는다.
- 실제 GPS 위치가 있고 지도 화면이 보일 때 현재 표시 범위만 요청한다. 기본 사전 다운로드를 중단한다.
- 정상 PNG만 사용한다. 403/429 응답 이미지는 화면과 캐시에 사용하지 않고 연결 제한 안내를 표시한다.
- 정상 타일은 SQLite 캐시로 재사용한다. HTTP 캐시 기한과 ETag/Last-Modified를 사용하며 헤더가 없으면 7일간 재사용한다.
- 기본 캐시는 `~/.cache/walker-safety/map-tiles.sqlite3`다. 차단 시 최소 60초 및 Retry-After, 그 외 연결 오류 시 30초 뒤 현재 지도 화면에서 재시도한다.
- 지도 저작자 표시를 유지한다. 연결 오류가 있어도 GPS 좌표 수신/표시와 안전감시 프로세스는 계속 동작한다.

코드/개발 PC 검증과 Pi 실제 표시 확인은 구분한다. 적절한 요청이라도 서버 또는 네트워크 자체 제한으로 접근이 거부될 수 있다.
그 경우 요청을 반복하거나 IP/식별정보를 바꾸며 우회하지 않고 응답 상태와 해당 서비스 이용 조건을 확인한다.
전체 지역 사전 다운로드나 오프라인 지도 제작 기능은 추가하지 않는다.

개발 PC에서 앱 식별정보를 사용한 세계 지도 타일 1개의 정상 PNG 응답을 확인했다.
공식 TkinterMapView 소스의 기존 요청 경로에서 HTTP 403 PNG가 정상 이미지처럼 표시/캐시되는 문제를 모의 응답으로 재현했다.
수정된 실제 Tk 위젯은 별도 HTTP 모의 응답으로 타일 렌더링과 앱 식별정보 사용을 확인했다.
Pi에서 새 프로세스를 실행한 뒤의 지도 표시 결과는 아직 확인하지 않았다.

공식 정책: [OSM tile usage policy](https://operations.osmfoundation.org/policies/tiles/).
서버를 바꾸려면 `config_local.py`의 MAP_TILE_URL과 MAP_ATTRIBUTION을 함께 해당 서비스 조건에 맞게 지정한다.

## Pi 적용

Pi PuTTY에서 실행한다. 안전감시 시험 프로세스는 실행 중이어도 유지할 수 있다.

```bash
git -C "$HOME/capstone" pull --ff-only origin main
```

GUI 프로세스를 다시 시작해야 새 지도 요청이 적용된다. 현재 실행 중인 GUI를 닫고,
데스크톱 자동 실행 래퍼가 다시 띄우면 센서 상세 보기에서 지도 배경을 확인한다.
래퍼가 없으면 Ubuntu 앱 실행에서 아래 명령을 실행한다. SSH 터미널에 임의의 DISPLAY 값을 지정하지 않는다.

```text
/usr/local/libexec/walker/start-pi-ui.sh
```

기존 라이브러리의 접근 차단 이미지는 프로세스 메모리에 남을 수 있으므로 코드 업데이트만으로 기존 창을 재사용하지 않는다.
정상 지도 배경과 현재 위치 마커, GPS 좌표를 확인한다. 여전히 제한 안내가 나오면 새 요청의 실제 Pi 응답 상태를 확인한다.
