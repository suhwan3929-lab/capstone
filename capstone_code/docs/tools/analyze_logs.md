# `tools/analyze_logs.py`

> **한 줄:** 시나리오별 충격량·기울기 분포를 표와 그래프로 보여준다.
> **계층:** 분석 도구 | **의존:** `config`, `console`, `pandas`, `matplotlib`

---

## 사용법

```bash
python tools/analyze_logs.py                # logs/ 전체
python tools/analyze_logs.py --dir logs
python tools/analyze_logs.py --no-plot      # 표만
```

## 출력

**표** — 시나리오별 최대 g, 최대 기울기, **충격 후 기울기**, 샘플 수

**판정** — 양성 최소값과 음성 최대값을 비교해 분리 가능 여부를 알려준다.

```
음성 최대: 3.60 g   /   양성 최소: 4.20 g
✅ 분리 가능. 권장 IMPACT_THRESHOLD_G = 3.90
```

분리되지 않으면 그것도 결과다 — "가속도만으로는 분리 불가"를 보이고
기울기 조건의 필요성을 논증하는 근거가 된다.

**그래프** — `logs/threshold_analysis.png` 로 저장.
상단에 가속도 시계열(현재 임계값 점선), 하단에 기울기 시계열(60° 점선).
양성 시나리오는 굵게, 음성은 얇고 흐리게 그린다.

## `replay.py` 와의 차이

| | `analyze_logs.py` | `replay.py` |
| :--- | :--- | :--- |
| 보는 것 | **원시 신호의 분포** | **판정 결과** |
| 방식 | 통계·그래프 | 실제 FSM 재생 |
| 용도 | "신호가 분리되는가" | "이 임계값으로 몇 개 맞추는가" |

**둘 다 필요하다.** 먼저 `analyze_logs` 로 신호가 분리되는지 보고,
`replay --sweep` 으로 최적 임계값을 찾는다.

## 고칠 때 주의

- ⚠ 이 도구는 CSV의 `t`, `accel_g`, `roll_deg`, `pitch_deg`, `tilt_deg` 열을 읽는다.
  `csv_logger.HEADER` 를 바꾸면 여기도 확인할 것.
- `pandas` / `matplotlib` 이 없으면 안내 메시지를 내고 종료한다. 죽지 않는다.
- 양성 판정은 파일명 접두사 `tipover` 기준 (`POSITIVE_PREFIXES`).
