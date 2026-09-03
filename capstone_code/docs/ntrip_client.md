# `ntrip_client.py`

> **한 줄:** RTK 보정정보(RTCM3)를 캐스터에서 받아 ZED-F9P로 흘려보낸다.
> **계층:** 부가 | **의존:** `config`, `sensors.gps_sensor`

---

## 왜 존재하는가

**이것 없이는 F9P가 RTK로 동작하지 않는다.** 계획서가 내세운 "cm 단위 정밀 위치"는
성립하지 않고, 측위 품질은 단독측위(수 m)에 머문다.

계획서 §6.2에 "국토지리정보원 VRS NTRIP 연동"이 적혀 있었으나 미구현 상태였다.

## 동작

1. 캐스터에 TCP 접속 → 마운트포인트 스트림 요청 (NTRIP v1/v2, Basic 인증)
2. 받은 RTCM3 바이트를 `gps_sensor.write_rtcm()` 으로 넘긴다
3. **VRS(가상기준점) 방식은 로버의 현재 위치를 주기적으로 되올려야 한다**
   → `gps_sensor.last_gga()` 로 마지막 원시 GGA 문장을 가져와 업로드
4. 끊기면 지수 백오프로 재접속 (최대 `NTRIP_MAX_BACKOFF`)

## 공개 인터페이스

```python
is_configured()                 # 설정이 완전한가
start(log_callback)             # 감시 스레드 기동
stop()
stats()                         # {connected, bytes, rtcm_age, healthy, reconnects, error}
fetch_sourcetable(host, port)   # 진단: 마운트포인트 목록
print_sourcetable()             # 위를 보기 좋게 출력
```

`stats()["healthy"]` 는 **보정정보가 실제로 흐르고 있는가**를 뜻한다
(연결됨 + 마지막 RTCM이 30초 이내). 단순 연결 여부보다 이 값이 의미 있다.

## 설정 (전부 환경변수)

```
WALKER_NTRIP=1
NTRIP_HOST=<캐스터 주소>
NTRIP_PORT=2101
NTRIP_MOUNTPOINT=<마운트포인트>
NTRIP_USER=... / NTRIP_PASS=...
```

마운트포인트를 모르면:

```bash
python -c "import ntrip_client as n; n.print_sourcetable()"
```

## 고칠 때 주의

- ⚠ **계정 정보를 소스에 적지 말 것.** 환경변수로만 받는다.
- ⚠ **RTCM을 시리얼 포트에 직접 쓰지 않는다.** `gps_sensor` 의 큐를 경유한다.
  포트를 소유한 스레드가 한 곳뿐이어야 경합이 없다.
- ⚠ **GGA는 받은 문장을 그대로 되올린다.** 직접 만들면 체크섬·포맷 오류가 나기 쉽다.
- 소켓 타임아웃은 정상이다(보정정보가 잠시 없을 수 있음). 연결을 끊지 말 것.

## 미해결 / 주의

- ⚠ **로버에 상시 인터넷 회선(LTE)이 필요하다.** 현재 BOM에 모뎀이 없다.
  Wi-Fi만으로는 실외 보행 중 보정정보를 받을 수 없다.
- ⚠ **VRS는 사용자의 위치를 캐스터 서버로 전송한다.** 개인정보 처리 항목에 명시할 것.
- 도심 협곡에서는 RTK FIX가 풀려 FLOAT로 떨어진다. 측위 품질을 알림에 함께 보내는 이유.
