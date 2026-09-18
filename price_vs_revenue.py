#!/usr/bin/env python3
"""CRCL 주가와 Circle 매출을 같은 시간축에 놓고 본다.

주가(달러)와 매출(달러)은 단위가 같아 보이지만 성격이 다르다 — 하나는 일별
자산 가격이고 하나는 분기 유량이다. 한 축에 겹치면 의미가 없으므로 축을 나눠
쌓고 시간축만 공유한다.

  위    주가 (일별) + 실적 공시일
  가운데 분기 매출 (RLDC / 유통비용)
  아래  시가총액 / TTM 매출 배수 — 매출 대비 얼마에 거래되는가

세 번째 패널이 핵심이다. 주가가 내려도 매출이 더 빨리 늘면 배수는 떨어진다.
주가 하락이 실적 악화 때문인지 밸류에이션 조정 때문인지는 이 배수가 가른다.

데이터 출처: Yahoo Finance · SEC EDGAR · DefiLlama · FRED

사용 예:
  python price_vs_revenue.py
  python price_vs_revenue.py --refresh
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

import circle_data as cd
from revenue_model import build, visible

PRICE_COLOR = "#4a3aa7"    # slot 7 violet
RLDC_COLOR = "#2a78d6"     # slot 1 blue
DIST_COLOR = "#eb6834"     # slot 2 orange
MULTIPLE_COLOR = "#1baf7a" # slot 3 aqua


def quarter_mid(q: cd.Quarter) -> datetime:
    start = datetime(q[0], (q[1] - 1) * 3 + 1, 15, tzinfo=timezone.utc)
    return start + timedelta(days=30)


def quarter_end(q: cd.Quarter) -> datetime:
    return (datetime(q[0] + 1, 1, 1, tzinfo=timezone.utc) if q[1] == 4
            else datetime(q[0], q[1] * 3 + 1, 1, tzinfo=timezone.utc)) - timedelta(days=1)


def price_on(prices: cd.Series, when: datetime) -> float | None:
    """해당일 이전의 가장 가까운 종가. 휴장일과 분기말 주말을 흡수한다."""
    earlier = [v for d, v in prices if d <= when]
    return earlier[-1] if earlier else None


def shares_on(shares: cd.Series, when: datetime) -> float | None:
    """해당 시점의 발행주식수. 공시 사이 구간은 직전 값을 끌고 간다.

    첫 공시보다 앞선 시점은 그 첫 값으로 근사한다 (상장 직후 한 분기).
    """
    if not shares:
        return None
    earlier = [v for d, v in shares if d <= when]
    return earlier[-1] if earlier else shares[0][1]


def multiples(results, prices, shares):
    """(분기, 시가총액, TTM 매출, 배수) — TTM 4개 분기가 다 있는 분기만."""
    by_q = {r.quarter: r for r in results}
    out = []
    for r in results:
        count = shares_on(shares, quarter_end(r.quarter))
        price = price_on(prices, quarter_end(r.quarter))
        if not (count and price):
            continue
        # 직전 4개 분기 매출 합계 (TTM)
        window = []
        q = r.quarter
        for _ in range(4):
            if q not in by_q:
                break
            window.append(by_q[q].revenue)
            q = (q[0] - 1, 4) if q[1] == 1 else (q[0], q[1] - 1)
        if len(window) < 4:
            continue
        cap, ttm = count * price, sum(window)
        out.append((r.quarter, cap, ttm, cap / ttm))
    return out


def plot(results, prices, filings, mults, out_path):
    fig, (ax_px, ax_rev, ax_mult) = plt.subplots(
        3, 1, figsize=(12, 9.6), dpi=160, sharex=True,
        gridspec_kw={"height_ratios": [1.5, 1.2, 1]})
    fig.patch.set_facecolor(cd.SURFACE)

    # 상장일이 낀 분기 전체가 들어오도록 그 분기 시작으로 맞춘다
    first = cd.quarter_of(prices[0][0])
    lo = datetime(first[0], (first[1] - 1) * 3 + 1, 1, tzinfo=timezone.utc)
    hi = prices[-1][0] + timedelta(days=25)

    # --- 위: 주가 -------------------------------------------------------
    cd.style_axes(ax_px)
    xs = [d for d, _ in prices]
    ys = [v for _, v in prices]
    ax_px.plot(xs, ys, color=PRICE_COLOR, linewidth=2, solid_capstyle="round", zorder=3)
    ax_px.fill_between(xs, ys, color=PRICE_COLOR, alpha=0.08, linewidth=0, zorder=2)
    ax_px.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax_px.set_ylim(0, max(ys) * 1.22)
    ax_px.set_ylabel("CRCL 주가", fontsize=10, color=cd.INK_SECONDARY, labelpad=10)

    peak_at, peak = max(prices, key=lambda p: p[1])
    trough_at, trough = min(prices, key=lambda p: p[1])
    for when, value, text, va in ((peak_at, peak, f"고점 ${peak:,.0f}", "bottom"),
                                  (trough_at, trough, f"저점 ${trough:,.0f}", "top")):
        ax_px.annotate(cd.tex_safe(f"{text}\n{when:%Y-%m}"), xy=(when, value),
                       xytext=(0, 9 if va == "bottom" else -9),
                       textcoords="offset points", fontsize=9, color=cd.INK_PRIMARY,
                       ha="center", va=va, linespacing=1.4, zorder=5)
    ax_px.annotate(cd.tex_safe(f"  현재 ${ys[-1]:,.0f}"), xy=(xs[-1], ys[-1]),
                   xytext=(6, 0), textcoords="offset points", fontsize=9.5,
                   color=cd.INK_PRIMARY, va="center", ha="left", zorder=5)

    for when in sorted(filings.values()):
        if lo <= when <= hi:
            ax_px.axvline(when, color=cd.INK_MUTED, linewidth=1,
                          linestyle=(0, (4, 3)), zorder=1)
    ax_px.annotate("점선 = 분기 실적 공시일", xy=(0.0, 1.0), xycoords="axes fraction",
                   xytext=(0, 6), textcoords="offset points", fontsize=9,
                   color=cd.INK_SECONDARY, va="bottom", ha="left")

    # --- 가운데: 분기 매출 ----------------------------------------------
    cd.style_axes(ax_rev)
    shown = [r for r in results if lo <= quarter_mid(r.quarter) <= hi]
    width = 62
    for r in shown:
        x = quarter_mid(r.quarter)
        hatch = "//" if r.reserve_income is None else None
        ax_rev.bar([x], [r.rldc], width=width, color=RLDC_COLOR, hatch=hatch,
                   edgecolor=cd.SURFACE, linewidth=0 if hatch is None else 2, zorder=3)
        # 인접한 두 채움 사이에 2px 상당의 표면색 간격을 둔다
        ax_rev.bar([x], [r.dist_amount], width=width, bottom=[r.rldc], color=DIST_COLOR,
                   hatch=hatch, edgecolor=cd.SURFACE, linewidth=2, zorder=3)
        ax_rev.annotate(cd.tex_safe(cd.human(r.revenue)), xy=(x, r.revenue),
                        xytext=(0, 7), textcoords="offset points", fontsize=9,
                        color=cd.INK_PRIMARY, ha="center", va="bottom", zorder=5)

    peak_rev = max(r.revenue for r in shown)
    ax_rev.set_ylim(0, peak_rev * 1.32)
    ax_rev.yaxis.set_major_formatter(cd.money_formatter(peak_rev))
    ax_rev.set_ylabel("분기 매출", fontsize=10, color=cd.INK_SECONDARY, labelpad=10)
    handles = [Patch(facecolor=RLDC_COLOR, label="RLDC (Circle 몫)"),
               Patch(facecolor=DIST_COLOR, label="유통비용")]
    leg = ax_rev.legend(handles=handles, loc="upper left", frameon=False,
                        fontsize=9.5, ncol=2)
    for t in leg.get_texts():
        t.set_color(cd.INK_SECONDARY)

    # --- 아래: 시가총액 / TTM 매출 --------------------------------------
    cd.style_axes(ax_mult)
    pts = [(quarter_end(q), m) for q, _, _, m in mults if lo <= quarter_end(q) <= hi]
    if pts:
        ax_mult.plot([d for d, _ in pts], [v for _, v in pts], color=MULTIPLE_COLOR,
                     linewidth=2, marker="o", markersize=8,
                     markeredgecolor=cd.SURFACE, markeredgewidth=1.5, zorder=4)
        for d, v in pts:
            ax_mult.annotate(f"{v:.1f}x", xy=(d, v), xytext=(0, 10),
                             textcoords="offset points", fontsize=9,
                             color=cd.INK_PRIMARY, ha="center", va="bottom", zorder=5)
        ax_mult.set_ylim(0, max(v for _, v in pts) * 1.32)
    ax_mult.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}x"))
    ax_mult.set_ylabel("시가총액 / TTM 매출", fontsize=10,
                       color=cd.INK_SECONDARY, labelpad=10)

    ax_mult.set_xlim(lo, hi)
    ax_mult.xaxis.set_major_locator(mdates.MonthLocator(bymonth=(1, 4, 7, 10)))
    ax_mult.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax_mult.xaxis.set_minor_locator(mdates.MonthLocator())

    fig.suptitle("CRCL 주가 vs Circle 매출", fontsize=15, color=cd.INK_PRIMARY,
                 fontweight="bold", x=0.10, ha="left", y=0.982)
    cd.credit(fig, prices[-1][0], "Yahoo Finance · SEC EDGAR · DefiLlama · FRED")
    fig.subplots_adjust(left=0.10, right=0.92, top=0.93, bottom=0.07, hspace=0.30)
    cd.OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=cd.SURFACE)
    plt.close(fig)
    return out_path


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="주가와 매출 비교")
    p.add_argument("--rate-series", default="DTB3")
    p.add_argument("--refresh", action="store_true", help="캐시 무시하고 재수집")
    p.add_argument("--out", type=str, help="저장 경로")
    args = p.parse_args(argv)

    derived: set = set()
    results = visible(build(
        cd.fetch_supply(cd.COINS["usdc"], args.refresh),
        cd.fetch_short_rate(args.rate_series, args.refresh),
        cd.fetch_reserve_income(args.refresh, derived),
        cd.fetch_reported_revenue(args.refresh, derived),
        cd.fetch_distribution_costs(args.refresh, derived),
        derived))
    prices = cd.fetch_price(refresh=args.refresh)
    shares = cd.fetch_shares_outstanding(args.refresh)
    filings = cd.fetch_filing_dates(args.refresh)
    mults = multiples(results, prices, shares)

    peak_at, peak = max(prices, key=lambda x: x[1])
    trough_at, trough = min(prices, key=lambda x: x[1])
    print(f"\n  CRCL  {prices[0][0]:%Y-%m-%d} 상장 ~ {prices[-1][0]:%Y-%m-%d}")
    print(f"    고점 ${peak:,.2f} ({peak_at:%Y-%m-%d})   저점 ${trough:,.2f} "
          f"({trough_at:%Y-%m-%d})   현재 ${prices[-1][1]:,.2f}")
    print(f"    고점 대비 {prices[-1][1] / peak * 100 - 100:+.1f}%   "
          f"저점 대비 {prices[-1][1] / trough * 100 - 100:+.1f}%")

    print(f"\n  {'분기':7}{'분기말 주가':>12}{'시가총액':>11}{'TTM 매출':>11}{'배수':>8}"
          f"{'분기 매출':>11}{'전년비':>9}")
    by_q = {r.quarter: r for r in results}
    for q, cap, ttm, mult in mults:
        r = by_q[q]
        prev = by_q.get((q[0] - 1, q[1]))
        yoy = f"{r.revenue / prev.revenue * 100 - 100:+.0f}%" if prev else "—"
        price = price_on(prices, quarter_end(q))
        print(f"  {q[0]}Q{q[1]} {price:11,.2f}{cd.human(cap):>11}{cd.human(ttm):>11}"
              f"{mult:7.1f}x{cd.human(r.revenue):>11}{yoy:>9}")
    print("\n  * 시가총액 = 분기말 종가 x 직전 공시 표지의 발행주식수(클래스 합산)")

    if len(mults) >= 2:
        first, last = mults[0], mults[-1]
        print(f"\n  {first[0][0]}Q{first[0][1]} -> {last[0][0]}Q{last[0][1]}")
        print(f"    TTM 매출 {cd.human(first[2])} -> {cd.human(last[2])} "
              f"({last[2] / first[2] * 100 - 100:+.0f}%)")
        print(f"    시가총액 {cd.human(first[1])} -> {cd.human(last[1])} "
              f"({last[1] / first[1] * 100 - 100:+.0f}%)")
        print(f"    배수     {first[3]:.1f}x -> {last[3]:.1f}x "
              f"({last[3] / first[3] * 100 - 100:+.0f}%)")

    out = args.out or (cd.OUT_DIR / "price_vs_revenue.png")
    plot(results, prices, filings, mults, out)
    print(f"\n저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
