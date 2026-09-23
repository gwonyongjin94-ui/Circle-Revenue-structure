#!/usr/bin/env python3
"""CRCL의 실현 변동성과, 그걸로 그린 향후 주가 분포.

적정주가 범위를 내더라도 주가가 그 범위 안에 머문다는 보장은 없다. 얼마나
벗어날 수 있는지를 같은 단위로 보여주는 것이 변동성이다. 이 저장소의
valuation.py가 내는 밴드를 이 분포 위에 겹쳐 그려 둘을 나란히 본다.

  위    롤링 실현 변동성 (연율화)
  가운데 일간 수익률 분포 — 정규분포와 비교
  아래  향후 주가 분포 + 밸류에이션 밴드

분포는 기하 브라운 운동(로그 수익률이 정규분포)을 가정한 분위수다. 실제
수익률은 아래 히스토그램이 보여주듯 꼬리가 두꺼워서, 극단 구간은 이 가정이
과소평가한다. 예측이 아니라 "지금 변동성이 유지되면 이 정도 폭"이라는 뜻이다.

데이터 출처: Yahoo Finance · SEC EDGAR · DefiLlama · FRED

사용 예:
  python volatility.py
  python volatility.py --horizon 180 --window 90
"""

from __future__ import annotations

import argparse
import math
import statistics
from datetime import datetime, timedelta, timezone

import matplotlib.dates as mdates
import matplotlib.pyplot as plt

import circle_data as cd
from revenue_model import build, visible
from valuation import DERATED_FROM, band, history
from price_vs_revenue import shares_on

VOL_COLORS = {30: "#2a78d6", 90: "#eb6834"}   # slot 1 blue, slot 2 orange
DIST_COLOR = "#4a3aa7"     # slot 7 violet
VALUE_COLOR = "#1baf7a"    # slot 3 aqua
TRADING_DAYS = 252
QUANTILES = (0.05, 0.25, 0.50, 0.75, 0.95)


def log_returns(prices: cd.Series) -> list[tuple[datetime, float]]:
    return [(prices[i][0], math.log(prices[i][1] / prices[i - 1][1]))
            for i in range(1, len(prices))]


def rolling_vol(rets, window: int):
    """연율화 실현 변동성. 표본 구간이 채워진 날부터."""
    out = []
    for i in range(window, len(rets) + 1):
        chunk = [r for _, r in rets[i - window:i]]
        out.append((rets[i - 1][0], statistics.stdev(chunk) * math.sqrt(TRADING_DAYS) * 100))
    return out


def forward_distribution(spot: float, sigma: float, horizon_days: int, steps: int = 60):
    """기하 브라운 운동 가정의 분위수 경로.

    기대수익률을 0으로 둔다. 즉 기댓값은 현재가에 머물지만, 로그정규 분포가
    위로 길게 늘어지는 탓에 중앙값은 현재가보다 아래로 내려간다. 변동성이
    클수록 그 간격이 벌어진다.
    """
    paths = {q: [] for q in QUANTILES}
    # 표준정규 분위수 (역함수 근사 대신 알려진 값 사용)
    z = {0.05: -1.6449, 0.25: -0.6745, 0.50: 0.0, 0.75: 0.6745, 0.95: 1.6449}
    for step in range(steps + 1):
        t = horizon_days * step / steps / 365
        sd = sigma * math.sqrt(t)
        for q in QUANTILES:
            # 드리프트를 0으로 두면 중앙값이 현재가에 머문다
            paths[q].append(spot * math.exp(-0.5 * sd**2 + z[q] * sd))
    return paths


def plot(prices, rets, vols, spot, sigma, horizon, value_band, out_path):
    fig, (ax_vol, ax_hist, ax_fan) = plt.subplots(
        3, 1, figsize=(11.5, 9.8), dpi=160,
        gridspec_kw={"height_ratios": [1.1, 1, 1.4]})
    fig.patch.set_facecolor(cd.SURFACE)

    # --- 위: 롤링 변동성 ------------------------------------------------
    cd.style_axes(ax_vol)
    for offset, (window, series) in enumerate(vols.items()):
        ax_vol.plot([d for d, _ in series], [v for _, v in series],
                    color=VOL_COLORS[window], linewidth=2,
                    label=f"{window}일", zorder=3 + window // 30)
        # 최근값이 서로 가까워 겹치므로 위아래로 나눈다
        ax_vol.annotate(f"  {window}일 {series[-1][1]:.0f}%", xy=series[-1],
                        xytext=(4, 9 if offset == 0 else -9),
                        textcoords="offset points", fontsize=9,
                        color=cd.INK_PRIMARY, va="center", ha="left", zorder=5)
    peak = max(v for s in vols.values() for _, v in s)
    ax_vol.set_ylim(0, peak * 1.18)
    ax_vol.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax_vol.set_ylabel("연율화 변동성", fontsize=10, color=cd.INK_SECONDARY, labelpad=10)
    ax_vol.xaxis.set_major_locator(mdates.MonthLocator(bymonth=(1, 4, 7, 10)))
    ax_vol.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    leg = ax_vol.legend(loc="upper right", frameon=False, fontsize=9.5, ncol=2)
    for t in leg.get_texts():
        t.set_color(cd.INK_SECONDARY)

    # --- 가운데: 수익률 분포 --------------------------------------------
    cd.style_axes(ax_hist)
    values = [r * 100 for _, r in rets]
    ax_hist.hist(values, bins=46, color=DIST_COLOR, alpha=0.75, zorder=3)
    mu, sd = statistics.mean(values), statistics.stdev(values)
    span = max(abs(min(values)), abs(max(values)))
    step = span * 2 / 200
    curve_x = [-span + i * step for i in range(201)]
    scale = len(values) * (max(values) - min(values)) / 46
    curve_y = [scale / (sd * math.sqrt(2 * math.pi))
               * math.exp(-0.5 * ((x - mu) / sd) ** 2) for x in curve_x]
    ax_hist.plot(curve_x, curve_y, color=cd.INK_SECONDARY, linewidth=2,
                 linestyle=(0, (4, 3)), zorder=4)
    ax_hist.set_xlabel("일간 로그 수익률", fontsize=10, color=cd.INK_SECONDARY)
    ax_hist.set_ylabel("일수", fontsize=10, color=cd.INK_SECONDARY, labelpad=10)
    ax_hist.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:+.0f}%"))
    beyond = sum(1 for v in values if abs(v - mu) > 3 * sd)
    ax_hist.annotate(f"점선 = 같은 평균·표준편차의 정규분포\n"
                     f"3σ 밖 관측 {beyond}일 — 정규분포 기대치는 "
                     f"{len(values) * 0.0027:.1f}일",
                     xy=(0.0, 1.0), xycoords="axes fraction", xytext=(0, 6),
                     textcoords="offset points", fontsize=9,
                     color=cd.INK_SECONDARY, va="bottom", ha="left", linespacing=1.5)

    # --- 아래: 향후 분포 + 밸류에이션 밴드 ------------------------------
    cd.style_axes(ax_fan)
    paths = forward_distribution(spot, sigma, horizon)
    start = prices[-1][0]
    days = [start + timedelta(days=horizon * i / 60) for i in range(61)]
    for lo_q, hi_q, alpha in ((0.05, 0.95, 0.12), (0.25, 0.75, 0.20)):
        ax_fan.fill_between(days, paths[lo_q], paths[hi_q], color=DIST_COLOR,
                            alpha=alpha, linewidth=0, zorder=2)
    ax_fan.plot(days, paths[0.50], color=DIST_COLOR, linewidth=2, zorder=4)

    tail = [(d, v) for d, v in prices if d >= start - timedelta(days=200)]
    ax_fan.plot([d for d, _ in tail], [v for _, v in tail],
                color=cd.INK_SECONDARY, linewidth=2, zorder=3)

    lo, mid, hi = value_band
    ax_fan.axhspan(lo, hi, color=VALUE_COLOR, alpha=0.16, zorder=1)
    ax_fan.axhline(mid, color=VALUE_COLOR, linewidth=2, zorder=3)
    ax_fan.annotate(cd.tex_safe(f"밸류에이션 밴드 ${lo:,.0f}~${hi:,.0f}"),
                    xy=(0.0, 0.0), xycoords="axes fraction", xytext=(4, 6),
                    textcoords="offset points", fontsize=9, color=VALUE_COLOR,
                    fontweight="bold", va="bottom", ha="left", zorder=6)
    for q, label in ((0.95, "95%"), (0.50, "중앙"), (0.05, "5%")):
        ax_fan.annotate(cd.tex_safe(f"  {label} ${paths[q][-1]:,.0f}"),
                        xy=(days[-1], paths[q][-1]), xytext=(4, 0),
                        textcoords="offset points", fontsize=9,
                        color=cd.INK_PRIMARY, va="center", ha="left", zorder=6)

    ax_fan.set_ylim(0, max(paths[0.95][-1], max(v for _, v in tail)) * 1.10)
    ax_fan.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax_fan.set_ylabel("주가", fontsize=10, color=cd.INK_SECONDARY, labelpad=10)
    ax_fan.xaxis.set_major_locator(mdates.MonthLocator(bymonth=(1, 4, 7, 10)))
    ax_fan.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax_fan.annotate(f"변동성 {sigma * 100:.0f}% 유지, 기대수익률 0 가정  ·  "
                    f"음영 = 50% / 90% 구간\n"
                    f"기댓값은 현재가에 머물지만 중앙값은 내려간다 — "
                    f"로그정규 분포가 위로 길게 늘어지기 때문",
                    xy=(0.0, 1.0), xycoords="axes fraction", xytext=(0, 6),
                    textcoords="offset points", fontsize=9, linespacing=1.5,
                    color=cd.INK_SECONDARY, va="bottom", ha="left")

    fig.suptitle("CRCL 변동성과 향후 주가 분포", fontsize=15, color=cd.INK_PRIMARY,
                 fontweight="bold", x=0.10, ha="left", y=0.982)
    cd.credit(fig, prices[-1][0], "Yahoo Finance · SEC EDGAR")
    fig.subplots_adjust(left=0.10, right=0.90, top=0.93, bottom=0.06, hspace=0.46)
    cd.OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=cd.SURFACE)
    plt.close(fig)
    return out_path


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="실현 변동성과 향후 주가 분포")
    p.add_argument("--window", type=int, default=90,
                   help="분포에 쓸 변동성 표본 구간(거래일). 기본 90")
    p.add_argument("--horizon", type=int, default=365, help="전망 기간(일). 기본 365")
    p.add_argument("--refresh", action="store_true", help="캐시 무시하고 재수집")
    p.add_argument("--out", type=str, help="저장 경로")
    args = p.parse_args(argv)

    prices = cd.fetch_price(refresh=args.refresh)
    rets = log_returns(prices)
    spot = prices[-1][1]

    print(f"\n  CRCL ${spot:,.2f}   {prices[0][0]:%Y-%m-%d} 상장 이후 {len(rets)}거래일\n")
    print(f"  {'구간':12}{'연율화 변동성':>14}")
    for window in (30, 60, 90, 252, len(rets)):
        if len(rets) < window:
            continue
        sample = [r for _, r in rets[-window:]]
        label = "상장 이후" if window == len(rets) else f"{window}일"
        print(f"  {label:12}{statistics.stdev(sample) * math.sqrt(TRADING_DAYS) * 100:12.1f}%")

    values = [r for _, r in rets]
    mu, sd = statistics.mean(values), statistics.stdev(values)
    peak, mdd = 0.0, 0.0
    for _, price in prices:
        peak = max(peak, price)
        mdd = min(mdd, price / peak - 1)
    print(f"\n  일간 평균 {mu * 100:+.3f}%   일간 표준편차 {sd * 100:.2f}%   "
          f"최대낙폭 {mdd * 100:.1f}%")
    print(f"  3σ 밖 관측 {sum(1 for v in values if abs(v - mu) > 3 * sd)}일 "
          f"(정규분포 기대 {len(values) * 0.0027:.1f}일) — 꼬리가 두껍다")

    sigma = statistics.stdev([r for _, r in rets[-args.window:]]) * math.sqrt(TRADING_DAYS)
    paths = forward_distribution(spot, sigma, args.horizon)
    print(f"\n  향후 주가 분포 (변동성 {sigma * 100:.0f}% 유지, 기대수익률 0 가정)")
    print(f"    기댓값은 ${spot:,.0f}에 머물지만 중앙값은 아래로 내려간다 — "
          f"로그정규 분포의 왜도 때문이다.")
    print(f"    {'기간':8}{'5%':>9}{'25%':>9}{'중앙':>9}{'75%':>9}{'95%':>9}")
    for label, frac in (("1개월", 30), ("3개월", 91), ("6개월", 182), ("12개월", 365)):
        if frac > args.horizon:
            continue
        idx = round(60 * frac / args.horizon)
        cells = "".join(f"{paths[q][idx]:8,.0f} " for q in QUANTILES)
        print(f"    {label:8}{cells}")

    # valuation.py와 같은 방식으로 밸류에이션 밴드를 구해 분포 위에 겹친다
    derived: set = set()
    results = visible(build(
        cd.fetch_supply(cd.COINS["usdc"], args.refresh),
        cd.fetch_short_rate("DTB3", args.refresh),
        cd.fetch_reserve_income(args.refresh, derived),
        cd.fetch_reported_revenue(args.refresh, derived),
        cd.fetch_distribution_costs(args.refresh, derived), derived))
    shares = cd.fetch_shares_outstanding(args.refresh)
    hist = history(results, prices, shares)
    derated = [h for h in hist if h[0] >= DERATED_FROM]
    rldc_band = band([c / l for _, c, _, l in derated])
    count = shares[-1][1]
    value_band = tuple(hist[-1][3] * m / count for m in rldc_band)
    print(f"\n  밸류에이션 밴드 (TTM RLDC x {DERATED_FROM[0]}Q{DERATED_FROM[1]} 이후 배수)")
    print(f"    ${value_band[0]:,.0f} ~ ${value_band[2]:,.0f} (중앙 ${value_band[1]:,.0f})")
    width = (value_band[2] / value_band[0] - 1) * 100
    band_12m = (paths[0.95][-1] / paths[0.05][-1] - 1) * 100
    print(f"    밴드 폭 {width:.0f}%  vs  12개월 90% 구간 폭 {band_12m:.0f}%")
    print(f"    => 변동성이 밸류에이션 범위보다 {band_12m / width:.0f}배 넓다.")

    out = args.out or (cd.OUT_DIR / "volatility.png")
    plot(prices, rets, {w: rolling_vol(rets, w) for w in (30, 90)},
         spot, sigma, args.horizon, value_band, out)
    print(f"\n저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
