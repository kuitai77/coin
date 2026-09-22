# Binance + Jev 모의투자 연구 도구

바이낸스 BTCUSDT 선물 자료로 매매 조건을 검사하고, **사용자가 적은 조건을 Jev에 전달해 진입 허용·거절 및 조기 종료를 판단**하는 Python 프로그램입니다.

현재 제공하는 기능은 과거 모의투자(백테스트), 실제 시세의 판단 요청 미리보기, 실제 Jev API를 연결한 과거 모의투자입니다. **실거래·거래소 데모 주문·24시간 실시간 모의체결은 아직 구현하지 않았습니다.** Binance 비밀키가 필요하지 않으며 실주문 함수도 없습니다.

## 먼저 확인할 결과

[비교 보고서](reports/comparison.md)를 읽어 주세요. 세 가지 기본 전략은 비용 반영 후 모두 손실이었습니다. 현재 기본값은 비교용 출발점이며 검증된 수익 전략이 아닙니다. Jev API 키가 제공되지 않아, 보고된 성과에는 Jev가 포함되지 않았습니다.

저장소가 비어 있었으므로 기존 사용자 조건은 확인되지 않았습니다. `conditions.json`의 초기 조건은 대화에서 제안한 예시입니다.

## 1. 설치 — Windows PowerShell

Python 3.10 이상과 Git 설치 후 실행합니다.

```powershell
git clone https://github.com/kuitai77/coin.git
cd coin
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

macOS/Linux에서는 `python3 -m venv .venv` 후 `.venv/bin/python`을 사용합니다. 아래 명령의 `python`은 가상환경 Python을 뜻합니다. PowerShell에서는 위의 전체 실행 경로로 바꿔 실행하면 활성화 정책 변경이 필요 없습니다.

## 2. 내 조건을 넣는 곳

`conditions.json`을 텍스트 편집기로 수정합니다. JSON은 큰따옴표를 사용하고 마지막 항목 뒤에는 쉼표를 붙이지 않습니다.

- `indicators`: 이동평균 기간, 거래량 배수, RSI 기준 등 **코드가 정확히 계산할 숫자 조건**.
- `extra_entry_checks`: 모든 전략에 공통으로 추가할 **필수 숫자 조건**. 하나라도 미충족이면 Jev가 승인해도 진입하지 않습니다.
- `jev.entry_conditions`: Jev가 확인할 **진입 판단 기준 문장 목록**.
- `jev.exit_conditions`: Jev가 확인할 **조기 종료 판단 기준 문장 목록**.
- `stop_atr`, `target_atr`: 변동성(ATR)을 기준으로 한 손절·익절 거리.
- `risk_per_trade`: 거래당 목표 손실 예산. `0.005`는 잔고의 0.5%입니다. 가격 급변 시 실제 모의 손실이 이를 초과할 수 있습니다.
- `max_notional_equity_ratio`: 포지션 명목금액/잔고 상한. 이 연구 엔진에서는 최대 2입니다.

예: ATR이 가격의 1% 이내일 때만 진입하도록 강제하려면:

```json
"extra_entry_checks": [
  {"field": "atr_pct", "op": "lte", "value": 0.01}
]
```

`op`에는 `gt`(초과), `gte`(이상), `lt`(미만), `lte`(이하)를 사용할 수 있습니다. 사용 가능한 필드는 `close`, `ema20`, `ema50`, `ema200`, `atr`, `rsi`, `lower`, `upper`, `volume`, `atr_pct`, `volume_ratio`입니다. `ema20/50/200` 필드명은 역할 이름이며 실제 기간은 `indicators` 설정을 따릅니다. 이 추가 조건은 롱·숏 모두에 적용됩니다. 잘못된 필드나 값은 오류로 중단합니다.

Jev에 전달할 문장 예:

```json
"entry_conditions": [
  "제안된 매매 방향이 현재 전략 및 제공된 최근 캔들과 일치할 때만 ALLOW를 선택한다.",
  "필요한 정보가 없으면 UNKNOWN을 선택한다. 뉴스나 호가를 추측하지 않는다."
]
```

이는 설명 예시이며 수익성을 보장하는 조건이 아닙니다. 한국어도 보낼 수 있지만 TypeSafe는 영어에서 성능이 가장 좋다고 안내합니다. 같은 의미의 한국어/영어 조건도 결과를 검증해야 합니다. 정확한 수치 제한은 문장에만 쓰지 말고 숫자 설정에도 넣어 주세요.

## 3. 무료로 조건 전달 내용 확인

```powershell
python app.py inspect --strategy trend
```

바이낸스 공개 API에서 완료된 15분봉을 받아 지표와 Jev 요청 미리보기를 출력합니다. **이 명령만으로는 Jev를 호출하지 않습니다.** 결과는 `runtime/latest-decision.json`에 저장됩니다. 현재 포지션이 없는 상태의 일회성 확인입니다.

## 4. 실제 Jev 판단 연결

TypeSafe 계정에서 발급받은 키를 **내 PC의 환경변수**로 설정합니다. GitHub나 채팅에 키를 올리지 마세요.

```powershell
$env:TYPESAFE_API_KEY="여기에_본인_PC에서만_입력"
python app.py inspect --strategy trend --jev
```

`.env.example`은 설명용이며 자동으로 읽지 않습니다. 모델은 재현성을 위해 `jev-1.13.0`으로 고정했습니다. 실제 서비스 이용 권한과 API 비용은 TypeSafe 계정에 따릅니다.

Jev에는 완료된 최근 20개 캔들, 지표, 전략 설명, 설정한 문장 조건, 모의 포지션 정보만 보냅니다. 미래 캔들·실계좌 정보·Binance 비밀키는 보내지 않습니다.

- 진입: `ALLOW` + confidence 0.70 이상 + 선택 확률 0.80 이상 + 숫자 조건 충족일 때만 허용.
- 종료: `CLOSE`가 같은 임계값을 만족할 때 다음 봉 시가로 조기 종료를 모의 처리.
- `UNKNOWN`, 낮은 확신, API 실패: 신규 진입 금지. 기존 고정 손절·익절은 계속 적용.
- 이 임계값은 테스트 시작값입니다. confidence와 선택 확률은 수익 확률이나 검증된 승률이 아닙니다.
- 응답의 형식, 모델 버전, 확률 합계를 검증합니다. API 오류는 `runtime/jev-cache/errors.jsonl`에 비밀키 없이 기록합니다.

## 5. 과거 모의투자 비교

```powershell
python research/download.py
python research/backtest.py
```

2025년 8월~2026년 8월 공개 15분봉·펀딩비율 ZIP 26개를 다운로드합니다. 8월은 지표 초기화에 사용합니다. 세 전략의 전체·참고·평가 구간 및 체결 오차 스트레스 결과는 `research/results.json`과 구간별 거래/잔고 JSON으로 생성됩니다. 과거 데이터는 공개 다운로드로 재현할 수 있어 Git에 넣지 않았습니다.

Jev 없는 기준 전략 하나:

```powershell
python app.py replay --strategy trend --start 2026-06-01 --end 2026-09-01
```

같은 기간에서 **실제 Jev 응답을 사용한** 비교:

```powershell
python app.py replay --strategy trend --start 2026-06-01 --end 2026-09-01 --jev --max-calls 2000
```

`trend`는 추세 눌림목, `breakout`은 거래량 돌파, `range`는 횡보장 반등입니다. 결과는 `runtime/comparison.json`에 저장됩니다. 세 전략을 각각 실행하면 비교할 수 있습니다. 파일이 덮어써지므로 결과를 보관하려면 이름을 바꾸세요.

처음에는 짧은 기간으로 API 연결부터 확인하세요. 최대 호출 수에 도달하면 실행은 실패로 중단되고 완성된 비교 결과를 만들지 않습니다. 이전 결과 파일이 있을 수 있으므로 터미널 성공 여부와 결과 기간을 확인하세요. 동일한 요청은 로컬 캐시를 재사용합니다. 조건이나 상태가 달라지면 캐시 키가 달라집니다. 실패한 응답은 정상 응답으로 캐시하지 않습니다.

**과거 Jev 재생 결과도 전진 모의투자와 다릅니다.** 현재 모델이 과거 시장 사건을 학습했을 가능성과 API 지연을 다음 봉 체결가에 반영하지 못하는 문제가 있습니다. 따라서 과거 비교만으로 실거래에 전환해서는 안 됩니다. 다음 개발 단계는 앞으로 발생하는 자료로 지속 실행하는 모의체결과 주문 복구 검증입니다.

## 기본 전략 조건

| 전략 | 롱 진입 | 숏 진입 | 손절/익절 | 최대 보유 |
|---|---|---|---|---|
| 추세 눌림목 | EMA50 > EMA200, 종가 > EMA200, 이전 종가 ≤ EMA20에서 현재 종가 > EMA20으로 전환 | 부등호 반대 | ATR×1.5 / ATR×3 | 32봉(8시간) |
| 거래량 돌파 | 종가 > 이전 20봉 최고가, 거래량 > 이전 20봉 평균×1.2, 종가 > EMA200 | 종가 < 이전 20봉 최저가, 같은 거래량 조건, 종가 < EMA200 | ATR×1.5 / ATR×3 | 32봉 |
| 횡보장 반등 | EMA50·200 차이/종가 < 0.5%, 이전 종가가 하단 밴드 밖이고 현재 재진입, 이전 RSI < 35 | 상단 밴드 재진입, 이전 RSI > 65 | ATR×1.5 / ATR×1.5 | 32봉 |

이동평균은 지수이동평균, ATR/RSI는 14기간 지수 평활(alpha=1/14, 첫 관측값 초기화), 밴드는 20봉 평균±모집단 표준편차×2입니다. 확정 봉에서 신호를 만든 뒤 다음 봉 시가에서 불리한 체결 오차를 반영합니다.

## 검증

```powershell
python -m unittest discover -s tests -v
```

미래 캔들 참조 방지, 다음 봉 진입, 한 봉 내 손절/익절 동시 접촉, 펀딩 반영, AI 오류 시 손절 유지, 숫자 조건 및 응답 검증을 확인합니다. API 응답 테스트는 명시적인 테스트용 응답입니다. 실제 Jev 성과를 가장하지 않습니다.

## 주요 파일

- `conditions.json`: 사용자가 수정하는 매매·AI 조건
- `jev.py`: 공식 TypeSafe HTTP API 연결 및 응답 검증
- `app.py`: 실시간 시세 확인 및 Jev/비Jev 모의투자 비교 명령
- `research/backtest.py`: 조건 계산·과거 체결 시뮬레이션
- `research/download.py`: 바이낸스 공개 데이터 다운로드
- `reports/comparison.md`: 실제 실행한 규칙 기반 비교 및 한계

## 공식 참고 자료

- https://docs.typesafe.ai/api
- https://docs.typesafe.ai/models
- https://docs.typesafe.ai/confidence
- https://github.com/binance/binance-public-data
- https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info
