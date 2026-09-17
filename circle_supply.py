#!/usr/bin/env python3
"""Circle이 발행하는 스테이블코인의 유통량(발행잔액) 추이를 그래프로 그린다.

사용 예:
  python circle_supply.py                       # USDC/EURC/USYC 전체
  python circle_supply.py --coins usdc          # USDC만
  python circle_supply.py --start 2024-01-01    # 기간 지정
  python circle_supply.py --layout overlay      # 한 축에 겹치기
  python circle_supply.py --refresh             # 캐시 무시하고 재수집
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt

import circle_data as cd


def _draw_line(ax, key: str, series: cd.Series, label_last: bool = True) -> None:
    coin = cd.COINS[key]
    xs = [d for d, _ in series]
    ys = [v for _, v in series]
    ax.plot(xs, ys, color=coin.color, linewidth=2, solid_capstyle="round",
            label=coin.label, zorder=3)
    if label_last:
        # 직접 라벨 — 색만으로 식별하지 않게 하고, 대비가 낮은 색의 판독성을 보완한다
        ax.annotate(cd.tex_safe(f"  {coin.label}  {cd.human(ys[-1])}"),
                    xy=(xs[-1], ys[-1]), xytext=(6, 0), textcoords="offset points",
                    va="center", ha="left", fontsize=9.5,
                    color=cd.INK_PRIMARY, zorder=4)


def plot_overlay(datasets: dict[str, cd.Series], scale: str, out_path: Path) -> Path:
    """한 축에 겹쳐 그린다. 규모가 비슷한 시리즈 또는 단일 시리즈용."""
    fig, ax = plt.subplots(figsize=(12, 6.4), dpi=160)
    fig.patch.set_facecolor(cd.SURFACE)
    cd.style_axes(ax)
    cd.time_axis(ax)

    for key, series in datasets.items():
        _draw_line(ax, key, series)

    ax.set_yscale(scale)
    peak = max(v for s in datasets.values() for _, v in s)
    ax.yaxis.set_major_formatter(cd.money_formatter(peak))
    if scale == "linear":
        ax.set_ylim(bottom=0)

    names = " · ".join(cd.COINS[k].label for k in datasets)
    note = " (로그 스케일)" if scale == "log" else ""
    ax.set_title(f"Circle 발행 코인 유통량 — {names}", fontsize=15,
                 color=cd.INK_PRIMARY, fontweight="bold", loc="left", pad=16)
    ax.set_ylabel(f"유통량 (USD 환산){note}", fontsize=10,
                  color=cd.INK_SECONDARY, labelpad=10)

    if len(datasets) > 1:
        leg = ax.legend(loc="upper left", frameon=False, fontsize=9.5, ncol=len(datasets))
        for text in leg.get_texts():
            text.set_color(cd.INK_SECONDARY)

    cd.credit(fig, max(s[-1][0] for s in datasets.values()), "DefiLlama Stablecoins API")
    fig.subplots_adjust(left=0.10, right=0.86, top=0.88, bottom=0.11)
    cd.OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=cd.SURFACE)
    plt.close(fig)
    return out_path


def plot_facets(datasets: dict[str, cd.Series], out_path: Path) -> Path:
    """규모가 제각각인 시리즈는 축을 나눠 그린다.

    한 축에 몰아넣으면 작은 시리즈가 바닥에 깔리고, 로그로 피하면 큰 시리즈의
    실제 등락이 뭉개진다. 시간축만 공유하고 y축은 각자 갖게 한다.
    """
    n = len(datasets)
    fig, axes = plt.subplots(n, 1, figsize=(12, 2.5 * n + 1.4), dpi=160, sharex=True)
    axes = [axes] if n == 1 else list(axes)
    fig.patch.set_facecolor(cd.SURFACE)

    for ax, (key, series) in zip(axes, datasets.items()):
        coin = cd.COINS[key]
        cd.style_axes(ax)
        _draw_line(ax, key, series, label_last=False)
        ax.fill_between([d for d, _ in series], [v for _, v in series],
                        color=coin.color, alpha=0.10, linewidth=0, zorder=2)

        peak = max(v for _, v in series)
        ax.yaxis.set_major_formatter(cd.money_formatter(peak))
        ax.set_ylim(0, peak * 1.18)

        ax.annotate(cd.tex_safe(f"{coin.label}   현재 {cd.human(series[-1][1])}   "
                                f"최고 {cd.human(peak)}"),
                    xy=(0.0, 1.0), xycoords="axes fraction", xytext=(0, 8),
                    textcoords="offset points", fontsize=11, fontweight="bold",
                    color=cd.INK_PRIMARY, va="bottom", ha="left")
        # 색 식별을 돕는 표식 — 텍스트는 잉크색을 유지한다
        ax.annotate("●", xy=(1.0, 1.0), xycoords="axes fraction", xytext=(-2, 9),
                    textcoords="offset points", fontsize=11, color=coin.color,
                    va="bottom", ha="right")

    cd.time_axis(axes[-1])
    fig.suptitle("Circle 발행 코인 유통량", fontsize=15, color=cd.INK_PRIMARY,
                 fontweight="bold", x=0.10, ha="left", y=0.985)
    fig.supylabel("유통량 (USD 환산)", fontsize=10, color=cd.INK_SECONDARY, x=0.022)

    cd.credit(fig, max(s[-1][0] for s in datasets.values()), "DefiLlama Stablecoins API")
    fig.subplots_adjust(left=0.10, right=0.97, top=0.90, bottom=0.075, hspace=0.42)
    cd.OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=cd.SURFACE)
    plt.close(fig)
    return out_path


def choose_layout(datasets: dict[str, cd.Series]) -> str:
    """규모 차이가 5배를 넘으면 축을 나눈다."""
    peaks = [max(v for _, v in s) for s in datasets.values() if s]
    if len(peaks) < 2:
        return "overlay"
    return "facet" if max(peaks) / min(peaks) > 5 else "overlay"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Circle 발행 코인 유통량 차트")
    p.add_argument("--coins", default="usdc,eurc,usyc",
                   help="쉼표 구분 (기본: usdc,eurc,usyc)")
    p.add_argument("--start", type=cd.parse_date, help="시작일 YYYY-MM-DD")
    p.add_argument("--end", type=cd.parse_date, help="종료일 YYYY-MM-DD")
    p.add_argument("--layout", choices=("auto", "facet", "overlay"), default="auto",
                   help="facet=코인별 분할, overlay=한 축에 겹침 (기본: auto)")
    p.add_argument("--scale", choices=("linear", "log"), default="linear",
                   help="overlay 레이아웃에만 적용 (기본: linear)")
    p.add_argument("--refresh", action="store_true", help="캐시 무시하고 API 재호출")
    p.add_argument("--out", type=Path, help="저장 경로 (기본: output/circle_supply.png)")
    args = p.parse_args(argv)

    keys = [k.strip().lower() for k in args.coins.split(",") if k.strip()]
    unknown = [k for k in keys if k not in cd.COINS]
    if unknown:
        p.error(f"알 수 없는 코인: {', '.join(unknown)} (가능: {', '.join(cd.COINS)})")

    datasets: dict[str, cd.Series] = {}
    for key in keys:
        series = cd.clip(cd.fetch_supply(cd.COINS[key], args.refresh), args.start, args.end)
        if not series:
            print(f"  ! {cd.COINS[key].label}: 해당 기간 데이터 없음 — 건너뜀", file=sys.stderr)
            continue
        datasets[key] = series
        first, last = series[0], series[-1]
        print(f"  {cd.COINS[key].label:5} {len(series):5,}일  "
              f"{first[0]:%Y-%m-%d} {cd.human(first[1]):>9}  ->  "
              f"{last[0]:%Y-%m-%d} {cd.human(last[1]):>9}")

    if not datasets:
        print("데이터가 없습니다.", file=sys.stderr)
        return 1

    layout = choose_layout(datasets) if args.layout == "auto" else args.layout
    out = args.out or (cd.OUT_DIR / "circle_supply.png")
    (plot_facets(datasets, out) if layout == "facet"
     else plot_overlay(datasets, args.scale, out))

    print(f"\n레이아웃: {layout}\n저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
