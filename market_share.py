#!/usr/bin/env python3
"""USDC의 스테이블코인 시장 점유율 추이를 USDT와 나란히 그린다.

절대 발행잔액만 보면 시장 전체가 커져서 늘어난 것인지 경쟁에서 이겨서 늘어난
것인지 구분되지 않는다. 점유율은 그 둘을 분리한다.

  위  : USDC / USDT 점유율 (%)
  아래: 전체 시장 규모 — 점유율의 분모

데이터 출처: DefiLlama Stablecoins API (USD 페그 기준)

사용 예:
  python market_share.py
  python market_share.py --start 2021-01-01   # 구간 직접 지정
  python market_share.py --no-events
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

import matplotlib.pyplot as plt

import circle_data as cd

# USDC 점유율을 실제로 움직인 사건들. 금리가 아니라 이쪽이 주된 동인이다.
# 시장이 이보다 작던 초창기는 점유율이 소수 지갑에 좌우돼 의미가 없다
MIN_MARKET_USD = 10e9

EVENTS = [
    (datetime(2022, 9, 29, tzinfo=timezone.utc), "Binance\nUSDC 강제전환"),
    (datetime(2023, 3, 11, tzinfo=timezone.utc), "SVB 파산\n디페그"),
    (datetime(2025, 7, 18, tzinfo=timezone.utc), "GENIUS Act\n서명"),
]


def to_share(part: cd.Series, whole: cd.Series) -> cd.Series:
    """같은 날짜끼리 맞춰 비중(%)으로 환산한다."""
    denom = dict(whole)
    return [(day, value / denom[day] * 100)
            for day, value in part if denom.get(day)]


def plot(shares: dict[str, cd.Series], market: cd.Series, events, out_path):
    fig, (ax_top, ax_bot) = plt.subplots(
        2, 1, figsize=(12, 8.0), dpi=160, sharex=True,
        gridspec_kw={"height_ratios": [2, 1]})
    fig.patch.set_facecolor(cd.SURFACE)

    # --- 위: 점유율 -----------------------------------------------------
    cd.style_axes(ax_top)
    registry = {**cd.COINS, **cd.REFERENCE}
    for key, series in shares.items():
        coin = registry[key]
        xs = [d for d, _ in series]
        ys = [v for _, v in series]
        ax_top.plot(xs, ys, color=coin.color, linewidth=2,
                    solid_capstyle="round", label=coin.label, zorder=3)
        ax_top.annotate(f"  {coin.label}  {ys[-1]:.1f}%",
                        xy=(xs[-1], ys[-1]), xytext=(6, 0), textcoords="offset points",
                        va="center", ha="left", fontsize=9.5,
                        color=cd.INK_PRIMARY, zorder=4)

    top = max(v for s in shares.values() for _, v in s)
    ax_top.set_ylim(0, top * 1.30)
    ax_top.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax_top.set_ylabel("스테이블코인 시장 점유율", fontsize=10,
                      color=cd.INK_SECONDARY, labelpad=10)

    leg = ax_top.legend(loc="upper left", frameon=False, fontsize=9.5, ncol=len(shares))
    for text in leg.get_texts():
        text.set_color(cd.INK_SECONDARY)

    lo = min(d for s in shares.values() for d, _ in s)
    hi = max(d for s in shares.values() for d, _ in s)
    # 날짜가 가까운 라벨끼리 겹치므로 높이를 엇갈리게 놓는다
    visible = [(w, t) for w, t in events if lo <= w <= hi]
    span_days = max((hi - lo).days, 1)
    levels, prev = [], None
    for when, _ in visible:
        close = prev is not None and (when - prev).days / span_days < 0.18
        levels.append(1 - (levels[-1] if close else 0))
        prev = when

    for (when, label), level in zip(visible, levels):
        for ax in (ax_top, ax_bot):
            ax.axvline(when, color=cd.INK_MUTED, linewidth=1,
                       linestyle=(0, (4, 3)), zorder=1)
        ax_top.annotate(label, xy=(when, top * (1.28 - 0.16 * level)), xytext=(4, 0),
                        textcoords="offset points", fontsize=8.5,
                        color=cd.INK_SECONDARY, va="top", ha="left",
                        linespacing=1.4, zorder=4)

    # --- 아래: 분모 -----------------------------------------------------
    cd.style_axes(ax_bot)
    xs = [d for d, _ in market]
    ys = [v for _, v in market]
    ax_bot.plot(xs, ys, color=cd.INK_SECONDARY, linewidth=2,
                solid_capstyle="round", zorder=3)
    ax_bot.fill_between(xs, ys, color=cd.INK_SECONDARY, alpha=0.08,
                        linewidth=0, zorder=2)
    peak = max(ys)
    ax_bot.yaxis.set_major_formatter(cd.money_formatter(peak))
    ax_bot.set_ylim(0, peak * 1.15)
    ax_bot.set_ylabel("전체 시장 규모", fontsize=10, color=cd.INK_SECONDARY, labelpad=10)
    ax_bot.annotate(cd.tex_safe(f"  {cd.human(ys[-1])}"), xy=(xs[-1], ys[-1]),
                    xytext=(6, 0), textcoords="offset points", va="center",
                    ha="left", fontsize=9.5, color=cd.INK_PRIMARY, zorder=4)
    cd.time_axis(ax_bot)

    fig.suptitle("USDC 시장 점유율", fontsize=15, color=cd.INK_PRIMARY,
                 fontweight="bold", x=0.10, ha="left", y=0.975)
    cd.credit(fig, hi, "DefiLlama Stablecoins API")

    fig.subplots_adjust(left=0.10, right=0.86, top=0.91, bottom=0.085, hspace=0.16)
    cd.OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=cd.SURFACE)
    plt.close(fig)
    return out_path


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="USDC 시장 점유율 차트")
    p.add_argument("--start", type=cd.parse_date, help="시작일 YYYY-MM-DD")
    p.add_argument("--end", type=cd.parse_date, help="종료일 YYYY-MM-DD")
    p.add_argument("--no-events", action="store_true", help="사건 표시선 끄기")
    p.add_argument("--refresh", action="store_true", help="캐시 무시하고 재수집")
    p.add_argument("--out", type=str, help="저장 경로")
    args = p.parse_args(argv)

    market = cd.clip(cd.fetch_market(args.refresh), args.start, args.end)
    if args.start is None:
        # 분모가 유의미해지는 시점부터 자른다 (기본값일 때만)
        first = next((d for d, v in market if v >= MIN_MARKET_USD), None)
        if first:
            market = [(d, v) for d, v in market if d >= first]
            print(f"  (시장 규모 {cd.human(MIN_MARKET_USD)} 도달 시점 "
                  f"{first:%Y-%m}부터 표시)")
    shares = {}
    for key, coin in (("usdc", cd.COINS["usdc"]), ("usdt", cd.REFERENCE["usdt"])):
        series = cd.clip(cd.fetch_supply(coin, args.refresh),
                         args.start or market[0][0], args.end)
        shares[key] = to_share(series, market)

    for key, series in shares.items():
        label = {**cd.COINS, **cd.REFERENCE}[key].label
        peak_day, peak = max(series, key=lambda p: p[1])
        print(f"  {label:5} 현재 {series[-1][1]:5.1f}%   "
              f"최고 {peak:5.1f}% ({peak_day:%Y-%m})")
    print(f"  시장 전체 {cd.human(market[-1][1])}")

    events = [] if args.no_events else EVENTS
    out = args.out or (cd.OUT_DIR / "market_share.png")
    plot(shares, market, events, out)
    print(f"\n저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
