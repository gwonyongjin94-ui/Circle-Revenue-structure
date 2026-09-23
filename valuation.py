#!/usr/bin/env python3
"""배수 기반 주당가치 범위와, 현재 주가가 함의하는 기대치.

이 저장소의 모델은 준비금 수익과 RLDC까지는 시장 데이터로 계산한다. 거기서
주당가치로 넘어가려면 배수라는 가정이 하나 더 필요하고, 그 가정은 데이터가
정해주지 않는다. 그래서 단일 적정주가 대신 범위를 내고, 현재 주가가 어떤
배수를 함의하는지 역산해 나란히 둔다.

왜 이익 배수를 쓰지 않는가
  FY2025 영업손익은 -$96.4M이지만 주식보상이 $566.2M이다 (전년 $50.1M).
  상장에 따른 일시적 팽창이라 정상화 가정이 결과를 지배한다. 그래서 영업
  이익 배수 대신 매출과 RLDC 배수를 쓴다. 참고용으로 주식보상을 제외한
  조정 영업이익은 출력에 함께 적는다.

  위    시나리오별 주당가치 vs 현재 주가
  아래  역사적 배수 추이 — 재평가가 어디서 멈췄는지

데이터 출처: Yahoo Finance · SEC EDGAR · DefiLlama · FRED

사용 예:
  python valuation.py
  python valuation.py --growth=-20,-10,0,10,20
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

import matplotlib.dates as mdates
import matplotlib.pyplot as plt

import circle_data as cd
from revenue_model import build, visible
from price_vs_revenue import price_on, quarter_end, shares_on

REV_COLOR = "#2a78d6"      # slot 1 blue   — 매출 배수
RLDC_COLOR = "#eb6834"     # slot 2 orange — RLDC 배수
PRICE_COLOR = "#4a3aa7"    # slot 7 violet — 현재 주가

# 재평가가 끝난 뒤 구간만 배수 범위의 근거로 삼는다. 상장 직후의 19.5x/51.7x는
# 수급이 만든 값이라 기준으로 쓰기 어렵다.
DERATED_FROM = (2025, 4)


def history(results, prices, shares):
    """(분기, 시가총액, TTM 매출, TTM RLDC) — TTM 4개 분기가 다 있는 분기만."""
    by_q = {r.quarter: r for r in results}
    out = []
    for r in results:
        window, q = [], r.quarter
        for _ in range(4):
            if q not in by_q:
                break
            window.append(by_q[q])
            q = (q[0] - 1, 4) if q[1] == 1 else (q[0], q[1] - 1)
        if len(window) < 4:
            continue
        price = price_on(prices, quarter_end(r.quarter))
        count = shares_on(shares, quarter_end(r.quarter))
        if not (price and count):
            continue
        out.append((r.quarter, price * count,
                    sum(x.revenue for x in window), sum(x.rldc for x in window)))
    return out


def band(values: list[float]) -> tuple[float, float, float]:
    """(저, 중, 고) — 최솟값, 중앙값, 최댓값."""
    ordered = sorted(values)
    return ordered[0], ordered[len(ordered) // 2], ordered[-1]


def grid(base: float, multiples: tuple[float, float, float],
         growths: list[float], count: float):
    """성장률 x 배수 -> 주당가치."""
    return {(g, m): base * (1 + g / 100) * m / count
            for g in growths for m in multiples}


def plot(scenarios, current, hist, out_path):
    fig, (ax_val, ax_mult) = plt.subplots(
        2, 1, figsize=(11.5, 8.4), dpi=160,
        gridspec_kw={"height_ratios": [1.4, 1]})
    fig.patch.set_facecolor(cd.SURFACE)

    # --- 위: 시나리오별 주당가치 ----------------------------------------
    cd.style_axes(ax_val)
    labels, lows, mids, highs, colors = [], [], [], [], []
    for name, color, rows in scenarios:
        for growth, (lo, mid, hi) in rows:
            labels.append(f"{name}\n{growth:+.0f}%")
            lows.append(lo); mids.append(mid); highs.append(hi)
            colors.append(color)

    xs = list(range(len(labels)))
    for x, lo, hi, color in zip(xs, lows, highs, colors):
        ax_val.plot([x, x], [lo, hi], color=color, linewidth=6,
                    solid_capstyle="round", alpha=0.35, zorder=3)
    ax_val.scatter(xs, mids, s=60, c=colors, zorder=5,
                   edgecolor=cd.SURFACE, linewidth=1.5)
    for x, mid in zip(xs, mids):
        ax_val.annotate(cd.tex_safe(f"${mid:,.0f}"), xy=(x, mid), xytext=(0, 10),
                        textcoords="offset points", fontsize=9,
                        color=cd.INK_PRIMARY, ha="center", va="bottom", zorder=6)

    ax_val.axhline(current, color=PRICE_COLOR, linewidth=2, zorder=4)
    # 마지막 시나리오 라벨과 겹치므로 왼쪽 빈 구간에 둔다
    ax_val.annotate(cd.tex_safe(f"현재 주가 ${current:,.2f}"),
                    xy=(-0.6, current), xytext=(2, 6), textcoords="offset points",
                    fontsize=9.5, color=PRICE_COLOR, fontweight="bold",
                    ha="left", va="bottom", zorder=6)

    ax_val.set_xticks(xs)
    ax_val.set_xticklabels(labels, fontsize=9, color=cd.INK_SECONDARY, linespacing=1.5)
    ax_val.set_xlim(-0.7, len(xs) - 0.3)
    ax_val.set_ylim(0, max(highs + [current]) * 1.18)
    ax_val.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax_val.set_ylabel("주당가치", fontsize=10, color=cd.INK_SECONDARY, labelpad=10)
    ax_val.annotate("세로 막대 = 배수 범위(저~고), 점 = 중앙값.  "
                    "가로축은 향후 12개월 실적 가정",
                    xy=(0.0, 1.0), xycoords="axes fraction", xytext=(0, 6),
                    textcoords="offset points", fontsize=9,
                    color=cd.INK_SECONDARY, va="bottom", ha="left")

    # --- 아래: 역사적 배수 ----------------------------------------------
    cd.style_axes(ax_mult)
    days = [quarter_end(q) for q, _, _, _ in hist]
    for label, color, vals in (
            ("시총 / TTM 매출", REV_COLOR, [c / r for _, c, r, _ in hist]),
            ("시총 / TTM RLDC", RLDC_COLOR, [c / l for _, c, _, l in hist])):
        ax_mult.plot(days, vals, color=color, linewidth=2, marker="o", markersize=7,
                     markeredgecolor=cd.SURFACE, markeredgewidth=1.5,
                     label=label, zorder=4)
        ax_mult.annotate(f"  {vals[-1]:.1f}x", xy=(days[-1], vals[-1]), xytext=(4, 0),
                         textcoords="offset points", fontsize=9.5,
                         color=cd.INK_PRIMARY, va="center", ha="left", zorder=5)
    ax_mult.set_ylim(0, max(c / l for _, c, _, l in hist) * 1.18)
    ax_mult.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}x"))
    ax_mult.set_ylabel("배수", fontsize=10, color=cd.INK_SECONDARY, labelpad=10)
    ax_mult.xaxis.set_major_locator(mdates.MonthLocator(bymonth=(1, 4, 7, 10)))
    ax_mult.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    leg = ax_mult.legend(loc="upper right", frameon=False, fontsize=9.5)
    for t in leg.get_texts():
        t.set_color(cd.INK_SECONDARY)

    fig.suptitle("Circle 주당가치 범위와 현재 주가", fontsize=15, color=cd.INK_PRIMARY,
                 fontweight="bold", x=0.10, ha="left", y=0.978)
    cd.credit(fig, datetime.now(timezone.utc),
              "Yahoo Finance · SEC EDGAR · DefiLlama · FRED")
    fig.subplots_adjust(left=0.10, right=0.93, top=0.90, bottom=0.10, hspace=0.42)
    cd.OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=cd.SURFACE)
    plt.close(fig)
    return out_path


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="배수 기반 주당가치 범위")
    # 음수로 시작하는 값은 argparse가 옵션으로 오인하므로 --growth=... 형태로 쓴다
    p.add_argument("--growth", default="-10,0,10",
                   help="향후 12개월 실적 변화 시나리오(%%), 쉼표 구분. "
                        "음수를 쓸 때는 --growth=-20,0,20 처럼 등호로 붙일 것")
    p.add_argument("--refresh", action="store_true", help="캐시 무시하고 재수집")
    p.add_argument("--out", type=str, help="저장 경로")
    args = p.parse_args(argv)

    derived: set = set()
    results = visible(build(
        cd.fetch_supply(cd.COINS["usdc"], args.refresh),
        cd.fetch_short_rate("DTB3", args.refresh),
        cd.fetch_reserve_income(args.refresh, derived),
        cd.fetch_reported_revenue(args.refresh, derived),
        cd.fetch_distribution_costs(args.refresh, derived), derived))
    prices = cd.fetch_price(refresh=args.refresh)
    shares = cd.fetch_shares_outstanding(args.refresh)

    hist = history(results, prices, shares)
    current, count = prices[-1][1], shares[-1][1]
    ttm_rev, ttm_rldc = hist[-1][2], hist[-1][3]

    derated = [h for h in hist if h[0] >= DERATED_FROM]
    rev_band = band([c / r for _, c, r, _ in derated])
    rldc_band = band([c / l for _, c, _, l in derated])

    print(f"\n  현재 주가 ${current:,.2f}   주식수 {count / 1e6:.1f}M   "
          f"시가총액 {cd.human(current * count)}")
    print(f"  TTM 매출 {cd.human(ttm_rev)} ({current * count / ttm_rev:.1f}x)   "
          f"TTM RLDC {cd.human(ttm_rldc)} ({current * count / ttm_rldc:.1f}x)")
    print(f"\n  배수 범위 기준 구간: {DERATED_FROM[0]}Q{DERATED_FROM[1]} 이후 "
          f"({len(derated)}개 분기)")
    print(f"    시총/TTM 매출  {rev_band[0]:.1f} ~ {rev_band[2]:.1f}x "
          f"(중앙 {rev_band[1]:.1f}x)")
    print(f"    시총/TTM RLDC  {rldc_band[0]:.1f} ~ {rldc_band[2]:.1f}x "
          f"(중앙 {rldc_band[1]:.1f}x)")

    growths = [float(g) for g in args.growth.split(",") if g.strip()]
    rev_grid = grid(ttm_rev, rev_band, growths, count)
    rldc_grid = grid(ttm_rldc, rldc_band, growths, count)

    print(f"\n  시나리오별 주당가치")
    print(f"    {'실적 가정':10}{'매출 배수 기준':>26}{'RLDC 배수 기준':>26}")
    for g in growths:
        r = [rev_grid[(g, m)] for m in rev_band]
        l = [rldc_grid[(g, m)] for m in rldc_band]
        print(f"    {g:+8.0f}%   ${r[0]:6,.0f} ~ ${r[2]:6,.0f} (중 ${r[1]:6,.0f})"
              f"   ${l[0]:6,.0f} ~ ${l[2]:6,.0f} (중 ${l[1]:6,.0f})")

    # 참고: 주식보상을 제외한 조정 영업이익
    opex = cd.fetch_annual("OperatingExpenses", args.refresh)
    sbc = cd.fetch_annual("ShareBasedCompensation", args.refresh)
    oi = cd.fetch_annual("OperatingIncomeLoss", args.refresh)
    year = max(opex)
    print(f"\n  참고 — {year}년 손익 (이익 배수를 쓰지 않는 이유)")
    print(f"    영업손익 {cd.human(oi[year])}   영업비용 {cd.human(opex[year])}   "
          f"주식보상 {cd.human(sbc[year])}")
    print(f"    주식보상 제외 시 조정 영업이익 {cd.human(oi[year] + sbc[year])}")
    print(f"    전년 주식보상은 {cd.human(sbc[year - 1])}였다 — 상장에 따른 일시 팽창이라")
    print(f"    정상화 가정이 결과를 지배한다.")

    scenarios = [("매출 배수", REV_COLOR,
                  [(g, tuple(rev_grid[(g, m)] for m in rev_band)) for g in growths]),
                 ("RLDC 배수", RLDC_COLOR,
                  [(g, tuple(rldc_grid[(g, m)] for m in rldc_band)) for g in growths])]
    out = args.out or (cd.OUT_DIR / "valuation.png")
    plot(scenarios, current, hist, out)
    print(f"\n저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
