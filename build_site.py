#!/usr/bin/env python3
"""대시보드 한 장을 docs/index.html 로 만든다. GitHub Pages가 그대로 서빙한다.

차트는 이미 assets/ 에 있으므로 복사해서 참조만 한다. 숫자는 모델에서 다시
뽑아 본문에 직접 박는다 — 이미지 안의 숫자는 검색도 복사도 안 되기 때문이다.

update.sh 가 매일 이걸 같이 돌리므로 사이트도 차트와 같은 시점을 가리킨다.

사용 예:
  python build_site.py
"""

from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone

import circle_data as cd
import snapshot
from revenue_model import build, visible
from valuation import DERATED_FROM, band, history

DOCS = cd.ROOT / "docs"

CHARTS = [
    ("valuation.png", "주당가치 범위", "과거 배수 범위가 함의하는 주당가치와 현재 주가"),
    ("volatility.png", "변동성과 향후 주가 분포",
     "연율 변동성, 일간 수익률 분포, 향후 분포에 겹친 밸류에이션 밴드"),
    ("revenue_model.png", "분기 매출 — 모델 vs 공시",
     "잔액과 금리로 추정한 값을 공시 실적과 대조한다"),
    ("price_vs_revenue.png", "주가 vs 매출",
     "주가가 빠지는 동안 매출이 어떻게 움직였는지, 그리고 배수 변화"),
    ("reserves.png", "준비금 구성과 만기 구조",
     "매출이 금리를 얼마나 빨리 따라가는지를 결정하는 구조"),
    ("distribution_costs.png", "유통비용 상대방별 구성",
     "Coinbase 실효 배분율과 그 밖 파트너 비중"),
    ("supply_vs_rate_placebo.png", "발행잔액 vs 기준금리 (대조군 포함)",
     "금리가 발행잔액을 움직였는지 USDT 대조군으로 검증한다"),
    ("market_share.png", "시장 점유율", "USDC·USDT 점유율과 전체 시장 규모"),
    ("other_revenue.png", "기타 매출", "준비금 수익 외 매출의 추이와 구성"),
    ("circle_supply.png", "발행 코인 유통량", "Circle이 발행하는 코인별 유통량"),
]


def collect(refresh: bool = False) -> dict:
    s = snapshot.collect(refresh)
    derived: set = set()
    results = visible(build(
        cd.fetch_supply(cd.COINS["usdc"], False),
        cd.fetch_short_rate("DTB3", False),
        cd.fetch_reserve_income(False, derived),
        cd.fetch_reported_revenue(False, derived),
        cd.fetch_distribution_costs(False, derived), derived))
    prices = cd.fetch_price()
    shares = cd.fetch_shares_outstanding()
    reported = [h for h in history(results, prices, shares, reported_only=True)
                if h[0] >= DERATED_FROM]
    rldc_band = band([c / l for _, c, _, l in reported])
    count = shares[-1][1]
    s["value_band"] = tuple(s["ttm_rldc"] * m / count for m in rldc_band)
    s["multiple_band"] = rldc_band
    s["band_quarters"] = len(reported)
    s["last_reported"] = max(r.quarter for r in results if r.reserve_income is not None)
    s["results"] = results
    return s


def gauge(lo: float, mid: float, hi: float, price: float) -> str:
    """밴드와 현재가를 한 줄에 겹쳐 그린다. 현재가가 밴드 밖이어도 보이게 한다."""
    low = min(lo, price)
    high = max(hi, price)
    pad = (high - low) * 0.28 or 1.0
    left, right = low - pad, high + pad
    span = right - left

    def pct(v: float) -> float:
        return (v - left) / span * 100

    if price < lo:
        verdict = f"밴드 하단보다 {(1 - price / lo) * 100:.0f}% 아래"
        tone = "below"
    elif price > hi:
        verdict = f"밴드 상단보다 {(price / hi - 1) * 100:.0f}% 위"
        tone = "above"
    else:
        verdict = f"밴드 안 (하단에서 {(price - lo) / (hi - lo) * 100:.0f}% 지점)"
        tone = "inside"

    return f"""
    <div class="gauge" data-tone="{tone}">
      <div class="gauge-head">
        <div>
          <div class="gauge-label">주당가치 범위</div>
          <div class="gauge-range">${lo:,.0f} <span>~</span> ${hi:,.0f}</div>
          <div class="gauge-sub">중앙 ${mid:,.0f}</div>
        </div>
        <div class="gauge-now">
          <div class="gauge-label">현재 주가</div>
          <div class="gauge-price">${price:,.2f}</div>
          <div class="gauge-verdict">{verdict}</div>
        </div>
      </div>
      <div class="track">
        <div class="track-band" style="left:{pct(lo):.2f}%;width:{pct(hi) - pct(lo):.2f}%"></div>
        <div class="track-mid" style="left:{pct(mid):.2f}%"></div>
        <div class="track-now" style="left:{pct(price):.2f}%"></div>
      </div>
      <div class="track-axis">
        <span style="left:{pct(lo):.2f}%">${lo:,.0f}</span>
        <span style="left:{pct(hi):.2f}%">${hi:,.0f}</span>
      </div>
    </div>"""


def tiles(s: dict) -> str:
    q = f"{s['quarter'][0]}Q{s['quarter'][1]}"
    items = [
        ("USDC 유통량", cd.human(s["supply"][1]), f"{s['supply'][0]:%Y-%m-%d}"),
        ("시가총액", cd.human(s["market_cap"]),
         f"TTM 매출 {s['market_cap'] / s['ttm_revenue']:.1f}x"),
        (f"{q} 총매출 추정", cd.human(s["revenue"]),
         f"준비금 수익 {cd.human(s['reserve_income'])}"),
        ("RLDC (Circle 몫)", cd.human(s["rldc"]),
         f"유통비용 {s['dist_ratio'] * 100:.0f}% 차감 후"),
        ("분기 평균 단기금리", f"{s['avg_rate']:.2f}%", "3개월 국채"),
        ("준비금 익일물 비중", f"{s['repo_share'] * 100:.0f}%",
         f"펀드 {cd.human(s['reserve_total'])}"),
    ]
    cells = "".join(
        f'<div class="tile"><div class="tile-label">{label}</div>'
        f'<div class="tile-value">{value}</div>'
        f'<div class="tile-note">{note}</div></div>'
        for label, value, note in items)
    return f'<div class="tiles">{cells}</div>'


def quarters_table(s: dict) -> str:
    rows = []
    for r in s["results"][-6:]:
        q = f"{r.quarter[0]}Q{r.quarter[1]}"
        actual = cd.human(r.reserve_income) if r.reserve_income is not None else "—"
        err = f"{r.error:+.1f}%" if r.error is not None else "—"
        mark = ' class="pending"' if r.reserve_income is None else ""
        rows.append(
            f"<tr{mark}><td>{q}</td><td>{cd.human(r.avg_aum)}</td>"
            f"<td>{r.avg_rate:.2f}%</td><td>{cd.human(r.modeled_ri)}</td>"
            f"<td>{actual}</td><td>{err}</td><td>{cd.human(r.revenue)}</td>"
            f"<td>{cd.human(r.rldc)}</td></tr>")
    return f"""
    <table>
      <thead><tr><th>분기</th><th>평균 잔액</th><th>금리</th><th>모델 준비금수익</th>
      <th>공시</th><th>오차</th><th>총매출</th><th>RLDC</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>"""


def render(s: dict) -> str:
    lo, mid, hi = s["value_band"]
    q = f"{s['quarter'][0]}Q{s['quarter'][1]}"
    last = f"{s['last_reported'][0]}Q{s['last_reported'][1]}"
    sections = "".join(
        f"""<section class="chart">
          <h3>{title}</h3>
          <p>{note}</p>
          <a href="assets/{name}"><img src="assets/{name}" alt="{title}" loading="lazy"></a>
        </section>""" for name, title, note in CHARTS)

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Circle Revenue Structure</title>
<meta name="description" content="Circle(USDC 발행사)의 수익 구조를 공개 데이터로 추적하는 대시보드">
<style>
:root {{
  color-scheme: light;
  --bg: #fcfcfb; --surface: #ffffff; --line: #e6e5e1;
  --ink: #0b0b0b; --ink-2: #52514e; --ink-3: #8a8985;
  --blue: #2a78d6; --orange: #eb6834; --aqua: #1baf7a; --violet: #4a3aa7;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    color-scheme: dark;
    --bg: #1a1a19; --surface: #232322; --line: #383835;
    --ink: #ffffff; --ink-2: #c3c2b7; --ink-3: #8a8985;
    --blue: #3987e5; --orange: #d95926; --aqua: #199e70; --violet: #9085e9;
  }}
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; background: var(--bg); color: var(--ink);
  font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo",
               "Pretendard", "Noto Sans KR", "Malgun Gothic", sans-serif;
  line-height: 1.6; -webkit-font-smoothing: antialiased;
}}
.wrap {{ max-width: 1040px; margin: 0 auto; padding: 0 16px 72px; }}
header {{ padding: 56px 0 28px; }}
h1 {{ font-size: clamp(26px, 5vw, 38px); margin: 0 0 8px; letter-spacing: -0.02em; }}
.lede {{ color: var(--ink-2); margin: 0; max-width: 62ch; }}
.stamp {{ color: var(--ink-3); font-size: 13px; margin-top: 14px; }}
h2 {{ font-size: 20px; margin: 48px 0 14px; letter-spacing: -0.01em; }}
h3 {{ font-size: 16px; margin: 0 0 4px; }}

.gauge {{
  background: var(--surface); border: 1px solid var(--line);
  border-radius: 14px; padding: 24px; margin-top: 8px;
}}
.gauge-head {{ display: flex; flex-wrap: wrap; gap: 20px; justify-content: space-between; }}
.gauge-label {{ font-size: 12px; color: var(--ink-3); letter-spacing: 0.02em; }}
.gauge-range {{ font-size: clamp(24px, 4vw, 32px); font-weight: 700; letter-spacing: -0.02em; }}
.gauge-range span {{ color: var(--ink-3); font-weight: 400; }}
.gauge-sub, .gauge-verdict {{ font-size: 13px; color: var(--ink-2); }}
.gauge-now {{ text-align: right; }}
.gauge-price {{ font-size: clamp(24px, 4vw, 32px); font-weight: 700; letter-spacing: -0.02em; }}
[data-tone="below"] .gauge-price, [data-tone="below"] .gauge-verdict {{ color: var(--orange); }}
[data-tone="above"] .gauge-price, [data-tone="above"] .gauge-verdict {{ color: var(--violet); }}
[data-tone="inside"] .gauge-price {{ color: var(--aqua); }}

.track {{
  position: relative; height: 16px; margin: 26px 0 6px;
  background: var(--line); border-radius: 8px;
}}
.track-band {{
  position: absolute; top: 0; height: 100%;
  background: var(--aqua); opacity: 0.32; border-radius: 8px;
}}
.track-mid {{ position: absolute; top: -4px; height: 24px; width: 2px; background: var(--aqua); }}
.track-now {{
  position: absolute; top: -8px; height: 32px; width: 4px; border-radius: 2px;
  background: var(--ink); box-shadow: 0 0 0 3px var(--surface);
}}
.track-axis {{ position: relative; height: 18px; font-size: 12px; color: var(--ink-3); }}
.track-axis span {{ position: absolute; transform: translateX(-50%); }}

.tiles {{
  display: grid; gap: 12px; margin-top: 8px;
  grid-template-columns: repeat(auto-fit, minmax(168px, 1fr));
}}
.tile {{
  background: var(--surface); border: 1px solid var(--line);
  border-radius: 12px; padding: 16px;
}}
.tile-label {{ font-size: 12px; color: var(--ink-3); }}
.tile-value {{ font-size: 22px; font-weight: 700; letter-spacing: -0.01em; margin: 2px 0; }}
.tile-note {{ font-size: 12px; color: var(--ink-2); }}

table {{ width: 100%; border-collapse: collapse; font-size: 14px; margin-top: 8px; }}
th, td {{ padding: 9px 10px; text-align: right; border-bottom: 1px solid var(--line); }}
th:first-child, td:first-child {{ text-align: left; }}
th {{ color: var(--ink-3); font-weight: 500; font-size: 12px; }}
tr.pending td {{ color: var(--ink-2); font-style: italic; }}
.scroll {{ overflow-x: auto; }}

.chart {{ margin-top: 36px; }}
.chart p {{ color: var(--ink-2); font-size: 14px; margin: 0 0 12px; }}
.chart img {{
  width: 100%; height: auto; display: block; border-radius: 12px;
  border: 1px solid var(--line); background: var(--surface);
}}
.note {{
  background: var(--surface); border: 1px solid var(--line);
  border-left: 3px solid var(--orange);
  border-radius: 10px; padding: 16px; margin-top: 20px;
  font-size: 14px; color: var(--ink-2);
}}
footer {{ margin-top: 56px; padding-top: 22px; border-top: 1px solid var(--line);
          font-size: 13px; color: var(--ink-3); }}
a {{ color: var(--blue); }}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>Circle Revenue Structure</h1>
  <p class="lede">
    Circle(USDC 발행사)의 수익 구조를 공개 데이터로 추적한다.
    매출은 사실상 <strong>단기금리 × 발행잔액</strong>으로 결정되고, 그 가운데
    약 {s['dist_ratio'] * 100:.0f}%가 유통비용으로 빠져나간다.
  </p>
  <p class="stamp">
    자동 갱신 · {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC ·
    <a href="https://github.com/gwonyongjin94-ui/Circle-Revenue-structure">GitHub</a>
  </p>
</header>

<h2>주당가치와 현재 주가</h2>
{gauge(lo, mid, hi, s['price'])}
<div class="note">
  밴드는 <strong>공시가 나온 {s['band_quarters']}개 분기</strong>({DERATED_FROM[0]}Q{DERATED_FROM[1]}~{last})의
  시총/TTM RLDC 배수 범위({s['multiple_band'][0]:.1f}~{s['multiple_band'][2]:.1f}x)를
  현재 TTM RLDC {cd.human(s['ttm_rldc'])}에 적용한 값이다.
  재평가가 끝난 구간만 쓰며, 상장 직후의 51.7x는 제외한다.
  <strong>적정가치가 아니라 "최근 시장이 매겨온 범위"</strong>라는 점에 주의할 것 —
  배수 자체가 바뀌면 밴드도 함께 움직인다.
  변동성이 연율 90%를 넘어 12개월 90% 구간은 이 밴드보다 수십 배 넓다.
</div>

<h2>지금 상태</h2>
{tiles(s)}

<h2>분기 실적 — 모델 추정과 공시</h2>
<div class="scroll">{quarters_table(s)}</div>
<div class="note">
  모델은 잔액과 금리만으로 준비금 수익을 계산한다. 공시가 나온 분기에서
  절대오차 평균 2% 수준이다. 기울임체 행은 아직 공시 전이라 모델값이다.
</div>

<h2>차트</h2>
{sections}

<footer>
  데이터 출처: DefiLlama · FRED · SEC EDGAR(CIK 1876042) · BlackRock USDXX · Yahoo Finance<br>
  공개 데이터로 만든 분석 도구다. 투자 판단이나 권유가 아니다.
  주당가치는 배수 가정에 전적으로 의존하고, 향후 주가 분포는 예측이 아니라
  현재 변동성이 유지될 경우의 조건부 서술이다.
</footer>
</div>
</body>
</html>
"""


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="대시보드 사이트 생성")
    p.add_argument("--refresh", action="store_true", help="캐시 무시하고 재수집")
    args = p.parse_args(argv)

    s = collect(args.refresh)
    (DOCS / "assets").mkdir(parents=True, exist_ok=True)
    copied = 0
    for name, _, _ in CHARTS:
        source = cd.ROOT / "assets" / name
        if source.exists():
            shutil.copy2(source, DOCS / "assets" / name)
            copied += 1
    (DOCS / "index.html").write_text(render(s), encoding="utf-8")
    (DOCS / ".nojekyll").write_text("")   # _ 로 시작하는 파일이 없어도 관행상 둔다

    lo, _, hi = s["value_band"]
    print(f"주당가치 ${lo:,.0f}~${hi:,.0f} · 현재 ${s['price']:,.2f} · 차트 {copied}장")
    print(f"저장: docs/index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
