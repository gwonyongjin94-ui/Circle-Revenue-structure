#!/usr/bin/env python3
"""Circle 발행잔액과 미 기준금리를 같은 시간축 위에 놓고 비교한다.

두 지표는 단위가 다르므로(달러 vs %) 축을 나눠 쌓는다. 하나의 그림에 y축을
둘 놓는 이중축 차트는 두 계열의 교차점이 눈금 선택에 따라 임의로 바뀌기 때문에
쓰지 않는다. 대신 시간축을 공유시키고, 금리 레짐(인상기/인하기)을 두 패널의
배경 띠로 깔아 시점을 맞춘다.

데이터 출처
  - DefiLlama Stablecoins API : 발행잔액
  - FRED DFF                  : 연방기금 실효금리

사용 예:
  python rate_overlay.py
  python rate_overlay.py --coins usdc --start 2021-01-01
  python rate_overlay.py --no-bands
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta

import matplotlib.pyplot as plt
from matplotlib.patches import Patch

import circle_data as cd

# 앞뒤 45일(=3개월 창) 사이에 이만큼 움직였으면 방향성 있는 레짐으로 본다 (%p)
REGIME_THRESHOLD = 0.15
REGIME_HALF_WINDOW_DAYS = 45
MIN_REGIME_DAYS = 60


def detect_regimes(rates: cd.Series) -> list[tuple[datetime, datetime, str]]:
    """금리 경로를 인상기/인하기/유지 구간으로 나눈다.

    각 날짜를 중심으로 앞뒤 45일의 변화량을 보고 방향을 분류한 뒤 연속 구간으로
    묶는다. 후행 창을 쓰면 구간 끝이 창 길이만큼 밀리므로 중심 창을 쓴다.
    FOMC 발표일을 하드코딩하지 않으므로 데이터가 갱신되면 구간도 따라 움직인다.
    """
    by_date = dict(rates)
    half = timedelta(days=REGIME_HALF_WINDOW_DAYS)
    labels: list[tuple[datetime, str]] = []
    for day, _ in rates:
        before, after = by_date.get(day - half), by_date.get(day + half)
        if before is None or after is None:
            continue
        delta = after - before
        if delta > REGIME_THRESHOLD:
            labels.append((day, "hike"))
        elif delta < -REGIME_THRESHOLD:
            labels.append((day, "cut"))
        else:
            labels.append((day, "hold"))

    spans: list[tuple[datetime, datetime, str]] = []
    for day, kind in labels:
        if spans and spans[-1][2] == kind:
            spans[-1] = (spans[-1][0], day, kind)
        else:
            spans.append((day, day, kind))

    return [s for s in spans
            if s[2] != "hold" and (s[1] - s[0]).days >= MIN_REGIME_DAYS]


def shade(ax, spans, alpha: float = 0.09) -> None:
    for start, end, kind in spans:
        ax.axvspan(start, end, color=cd.HIKE_TINT if kind == "hike" else cd.CUT_TINT,
                   alpha=alpha, linewidth=0, zorder=1)


def _draw_supply_panel(ax, series_map, registry, spans, ylabel):
    cd.style_axes(ax)
    shade(ax, spans)
    peak = max(v for s in series_map.values() for _, v in s)
    for key, series in series_map.items():
        coin = registry[key]
        xs = [d for d, _ in series]
        ys = [v for _, v in series]
        ax.plot(xs, ys, color=coin.color, linewidth=2,
                solid_capstyle="round", label=coin.label, zorder=3)
        ax.annotate(cd.tex_safe(f"  {coin.label}  {cd.human(ys[-1])}"),
                    xy=(xs[-1], ys[-1]), xytext=(6, 0), textcoords="offset points",
                    va="center", ha="left", fontsize=9.5,
                    color=cd.INK_PRIMARY, zorder=4)
    ax.yaxis.set_major_formatter(cd.money_formatter(peak))
    ax.set_ylim(0, peak * 1.12)
    ax.set_ylabel(ylabel, fontsize=10, color=cd.INK_SECONDARY, labelpad=10)


def plot(supply, rates, spans, out_path, placebo=None):
    rows = 3 if placebo else 2
    ratios = [2, 1.3, 1] if placebo else [2, 1]
    fig, axes = plt.subplots(rows, 1, figsize=(12, 8.2 + (2.6 if placebo else 0)),
                             dpi=160, sharex=True, gridspec_kw={"height_ratios": ratios})
    ax_top, ax_bot = axes[0], axes[-1]
    fig.patch.set_facecolor(cd.SURFACE)

    # --- 위: Circle 발행잔액 --------------------------------------------
    _draw_supply_panel(ax_top, supply, cd.COINS, spans, "발행잔액 (USD 환산)")

    # --- 가운데: 대조군 -------------------------------------------------
    if placebo:
        _draw_supply_panel(axes[1], placebo, cd.REFERENCE, spans, "대조군 발행잔액")
        axes[1].annotate(
            "대조군: 같은 금리 환경에 놓였지만 Circle이 발행하지 않는 계열.\n"
            "인상기에 같이 줄지 않았다면, 금리는 USDC 감소의 주된 원인이 아니다.",
            xy=(0.0, 1.0), xycoords="axes fraction", xytext=(0, 6),
            textcoords="offset points", fontsize=9, color=cd.INK_SECONDARY,
            va="bottom", ha="left", linespacing=1.5)

    handles = [Patch(facecolor=cd.HIKE_TINT, alpha=0.20, label="금리 인상기"),
               Patch(facecolor=cd.CUT_TINT, alpha=0.20, label="금리 인하기")]
    leg = ax_top.legend(handles=handles, loc="upper left", frameon=False,
                        fontsize=9.5, ncol=2)
    for text in leg.get_texts():
        text.set_color(cd.INK_SECONDARY)

    # --- 아래: 기준금리 -------------------------------------------------
    cd.style_axes(ax_bot)
    shade(ax_bot, spans)
    xs = [d for d, _ in rates]
    ys = [v for _, v in rates]
    ax_bot.plot(xs, ys, color=cd.RATE_COLOR, linewidth=2,
                solid_capstyle="round", zorder=3)
    ax_bot.annotate(f"  기준금리  {ys[-1]:.2f}%",
                    xy=(xs[-1], ys[-1]), xytext=(6, 0), textcoords="offset points",
                    va="center", ha="left", fontsize=9.5,
                    color=cd.INK_PRIMARY, zorder=4)
    ax_bot.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax_bot.set_ylim(0, max(ys) * 1.22)
    ax_bot.set_ylabel("연방기금 실효금리", fontsize=10, color=cd.INK_SECONDARY, labelpad=10)
    cd.time_axis(ax_bot)

    fig.suptitle("Circle 발행잔액 vs 미 기준금리", fontsize=15, color=cd.INK_PRIMARY,
                 fontweight="bold", x=0.10, ha="left", y=0.985 if placebo else 0.975)
    last = max(max(d for d, _ in s) for s in supply.values())
    cd.credit(fig, last, "DefiLlama Stablecoins API · FRED (DFF)")

    top = 0.93 if placebo else 0.91
    fig.subplots_adjust(left=0.10, right=0.86, top=top, bottom=0.075,
                        hspace=0.30 if placebo else 0.16)
    cd.OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=cd.SURFACE)
    plt.close(fig)
    return out_path


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="발행잔액과 기준금리 비교 차트")
    p.add_argument("--coins", default="usdc", help="쉼표 구분 (기본: usdc)")
    p.add_argument("--start", type=cd.parse_date, help="시작일 YYYY-MM-DD")
    p.add_argument("--end", type=cd.parse_date, help="종료일 YYYY-MM-DD")
    p.add_argument("--no-bands", action="store_true", help="레짐 배경 띠 끄기")
    p.add_argument("--placebo", action="store_true",
                   help="USDT 대조군 패널 추가 — 금리 해석이 성립하는지 검증용")
    p.add_argument("--refresh", action="store_true", help="캐시 무시하고 API 재호출")
    p.add_argument("--out", type=str, help="저장 경로")
    args = p.parse_args(argv)

    keys = [k.strip().lower() for k in args.coins.split(",") if k.strip()]
    unknown = [k for k in keys if k not in cd.COINS]
    if unknown:
        p.error(f"알 수 없는 코인: {', '.join(unknown)} (가능: {', '.join(cd.COINS)})")

    supply: dict[str, cd.Series] = {}
    for key in keys:
        series = cd.clip(cd.fetch_supply(cd.COINS[key], args.refresh), args.start, args.end)
        if series:
            supply[key] = series
        else:
            print(f"  ! {cd.COINS[key].label}: 해당 기간 데이터 없음 — 건너뜀", file=sys.stderr)
    if not supply:
        print("발행잔액 데이터가 없습니다.", file=sys.stderr)
        return 1

    # 금리는 발행잔액이 존재하는 구간으로 맞춘다
    lo = min(min(d for d, _ in s) for s in supply.values())
    hi = max(max(d for d, _ in s) for s in supply.values())
    rates = cd.clip(cd.fetch_fed_funds(args.refresh), args.start or lo, args.end or hi)
    if not rates:
        print("금리 데이터가 없습니다.", file=sys.stderr)
        return 1

    placebo = None
    if args.placebo:
        ref = cd.REFERENCE["usdt"]
        ps = cd.clip(cd.fetch_supply(ref, args.refresh), args.start or lo, args.end or hi)
        if ps:
            placebo = {"usdt": ps}
        else:
            print("  ! USDT: 해당 기간 데이터 없음 — 대조군 생략", file=sys.stderr)

    spans = [] if args.no_bands else detect_regimes(rates)
    for start, end, kind in spans:
        lo_r = next(v for d, v in rates if d >= start)
        hi_r = [v for d, v in rates if d <= end][-1]
        print(f"  {'인상기' if kind == 'hike' else '인하기'}  "
              f"{start:%Y-%m} ~ {end:%Y-%m}  {lo_r:.2f}% -> {hi_r:.2f}%")

    out = args.out or (cd.OUT_DIR / ("supply_vs_rate_placebo.png" if placebo
                                     else "supply_vs_rate.png"))
    plot(supply, rates, spans, out, placebo=placebo)
    print(f"\n저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
