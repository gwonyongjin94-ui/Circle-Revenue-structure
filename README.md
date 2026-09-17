# Circle Revenue Structure

Circle(USDC 발행사)의 수익 구조를 데이터로 뜯어보는 프로젝트.

Circle의 매출은 사실상 **준비금 운용수익 = 단기금리 x 발행잔액** 으로 결정된다.
준비금은 만기 93일 이내의 미 국채와 익일물 국채 레포로만 구성돼 듀레이션이
사실상 0이라, 금리가 바뀌면 가격이 아니라 이자수익이 움직인다.
그래서 이 저장소는 두 축을 추적한다.

- **발행잔액 (AUM)** — 현재 구현됨
- **준비금 구성과 단기금리** — 예정

## 발행량 차트

![Circle 발행 코인 유통량](assets/circle_supply.png)

USDC 단독으로 보면 2023년 3월 SVB 파산 당시의 급락($43B -> $32B)이 선명하다.

![USDC 유통량](assets/usdc_supply.png)

## 준비

```bash
python3 -m venv .venv
./.venv/bin/pip install matplotlib requests
```

## 실행

```bash
./.venv/bin/python circle_supply.py
```

`output/circle_supply.png` 생성. x축 시간, y축 유통량(USD 환산).

### 옵션

| 옵션 | 설명 | 기본값 |
|---|---|---|
| `--coins` | `usdc`, `eurc`, `usyc` 중 쉼표 구분 | 전체 |
| `--start` / `--end` | 기간 (`YYYY-MM-DD`) | 전체 |
| `--layout` | `facet`(코인별 분할) / `overlay`(한 축) / `auto` | `auto` |
| `--scale` | `linear` / `log` — overlay에만 적용 | `linear` |
| `--refresh` | 캐시 무시하고 API 재호출 | 꺼짐 |
| `--out` | 저장 경로 | `output/circle_supply.png` |

```bash
# USDC만, 2021년 이후
./.venv/bin/python circle_supply.py --coins usdc --start 2021-06-01

# 세 코인을 한 축에 로그로 겹쳐보기
./.venv/bin/python circle_supply.py --layout overlay --scale log
```

`--layout auto`는 시리즈 간 규모 차이가 5배를 넘으면 자동으로 축을 나눈다.
USDC($74B)와 EURC($473M)를 한 축에 놓으면 작은 쪽이 바닥에 깔리고,
로그로 피하면 USDC의 실제 등락(2023년 SVB 급락 등)이 뭉개지기 때문이다.

## 대상 코인

| 키 | 코인 | 성격 | 현재 유통량 |
|---|---|---|---|
| `usdc` | USDC | USD 페그 스테이블코인 | ~$74B |
| `eurc` | EURC | EUR 페그 스테이블코인 | ~$473M |
| `usyc` | USYC | 토큰화 국채 MMF (Hashnote 인수) | ~$2.6B |

EURC는 유로 페그라 원화 단위가 다르므로, 비교 가능하도록 API의 USD 환산값을 쓴다.

## 데이터

- 출처: [DefiLlama Stablecoins API](https://defillama.com/stablecoins) (무료, 인증 불필요)
- 응답은 `data/<코인>.json`에 캐시하며 12시간 지나면 자동 갱신한다.

## 로드맵

- [x] 발행 코인 유통량 시계열 차트
- [ ] 준비금 구성 (BlackRock USDXX CUSIP별 보유 국채, 만기 사다리)
- [ ] 기준금리 오버레이 — 금리와 발행잔액의 관계 검증
- [ ] USDT 대비 점유율 추이
- [ ] 준비금 운용수익 추정 모델
