#!/usr/bin/env python3
"""현재 수치를 SNAPSHOT.md 로 적는다.

차트 PNG는 하단 출처 줄에 날짜가 박혀 매일 바뀌므로, 자동 갱신을 걸면 데이터가
그대로여도 커밋이 생긴다. 그 커밋이 소음이 되지 않도록 핵심 수치를 텍스트로
남겨 커밋 diff에서 무엇이 달라졌는지 바로 보이게 한다.

사용 예:
  python snapshot.py
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

import circle_data as cd
from revenue_model import build, visible
from price_vs_revenue import quarter_end, price_on, shares_on
from valuation import DERATED_FROM, band, history


def collect(refresh: bool = False) -> dict:
    derived: set = set()
    results = visible(build(
        cd.fetch_supply(cd.COINS["usdc"], refresh),
        cd.fetch_short_rate("DTB3", refresh),
        cd.fetch_reserve_income(refresh, derived),
        cd.fetch_reported_revenue(refresh, derived),
        cd.fetch_distribution_costs(refresh, derived), derived))
    prices = cd.fetch_price(refresh=refresh)
    shares = cd.fetch_shares_outstanding(refresh)
    hist = history(results, prices, shares)

    current = results[-1]
    spot, count = prices[-1][1], shares[-1][1]
    derated = [h for h in hist if h[0] >= DERATED_FROM]
    rldc_band = band([c / l for _, c, _, l in derated])
    as_of, holdings = cd.fetch_reserves(refresh)
    total = sum(h.market_value for h in holdings)
    repo = sum(h.market_value for h in holdings if h.is_repo)

    return dict(
        quarter=current.quarter, supply=cd.fetch_supply(cd.COINS["usdc"], False)[-1],
        avg_aum=current.avg_aum, avg_rate=current.avg_rate,
        reserve_income=current.modeled_ri, revenue=current.revenue,
        distribution=current.dist_amount, rldc=current.rldc,
        dist_ratio=current.dist_ratio,
        price=spot, price_date=prices[-1][0], shares=count, market_cap=spot * count,
        ttm_revenue=hist[-1][2], ttm_rldc=hist[-1][3],
        value_band=tuple(hist[-1][3] * m / count for m in rldc_band),
        reserve_as_of=as_of, reserve_total=total, repo_share=repo / total,
    )


def render(s: dict) -> str:
    q = f"{s['quarter'][0]}Q{s['quarter'][1]}"
    lo, mid, hi = s["value_band"]
    return f"""# 스냅샷

자동 생성 — {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC

## 발행잔액

| | |
|---|---|
| USDC 유통량 | {cd.human(s['supply'][1])} ({s['supply'][0]:%Y-%m-%d}) |
| {q} 평균 잔액 | {cd.human(s['avg_aum'])} |
| {q} 평균 단기금리 | {s['avg_rate']:.2f}% |

## {q} 모델 추정

| | |
|---|---|
| 준비금 수익 | {cd.human(s['reserve_income'])} |
| 총매출 | {cd.human(s['revenue'])} |
| 유통비용 | {cd.human(s['distribution'])} ({s['dist_ratio'] * 100:.1f}%) |
| RLDC | {cd.human(s['rldc'])} |

## 준비금 ({s['reserve_as_of']:%Y-%m-%d} 기준)

| | |
|---|---|
| Circle Reserve Fund 규모 | {cd.human(s['reserve_total'])} |
| 익일물 레포 비중 | {s['repo_share'] * 100:.1f}% |

## 주가

| | |
|---|---|
| CRCL | ${s['price']:,.2f} ({s['price_date']:%Y-%m-%d}) |
| 시가총액 | {cd.human(s['market_cap'])} |
| TTM 매출 배수 | {s['market_cap'] / s['ttm_revenue']:.1f}x |
| TTM RLDC 배수 | {s['market_cap'] / s['ttm_rldc']:.1f}x |
| 주당가치 범위 | ${lo:,.0f} ~ ${hi:,.0f} (중앙 ${mid:,.0f}) |

숫자의 근거와 한계는 [README](README.md) 참조. 투자 판단이나 권유가 아니다.
"""


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="핵심 수치 스냅샷")
    p.add_argument("--refresh", action="store_true", help="캐시 무시하고 재수집")
    p.add_argument("--out", default="SNAPSHOT.md", help="저장 경로")
    args = p.parse_args(argv)

    s = collect(args.refresh)
    text = render(s)
    (cd.ROOT / args.out).write_text(text)

    q = f"{s['quarter'][0]}Q{s['quarter'][1]}"
    print(f"CRCL ${s['price']:,.2f} · {q} 매출 추정 {cd.human(s['revenue'])} · "
          f"USDC {cd.human(s['supply'][1])}")
    print(f"저장: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
