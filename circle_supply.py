#!/usr/bin/env python3
"""Circle이 발행하는 스테이블코인의 유통량(발행잔액) 추이를 그래프로 그린다.

데이터 출처: DefiLlama Stablecoins API (무료, 인증 불필요)
  https://stablecoins.llama.fi/stablecoincharts/all?stablecoin=<id>

사용 예:
  python circle_supply.py                       # USDC/EURC/USYC 전체
  python circle_supply.py --coins usdc          # USDC만
  python circle_supply.py --start 2024-01-01    # 기간 지정
  python circle_supply.py --scale linear        # 스케일 강제
  python circle_supply.py --refresh             # 캐시 무시하고 재수집
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # 화면 없는 환경에서도 저장 가능
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import requests
from matplotlib import font_manager


def _use_korean_font() -> None:
    """한글 라벨이 두부(□)로 깨지지 않도록 사용 가능한 한글 폰트를 잡는다."""
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for candidate in ("Apple SD Gothic Neo", "Malgun Gothic", "NanumGothic",
                      "Noto Sans KR", "AppleGothic", "Arial Unicode MS"):
        if candidate in installed:
            plt.rcParams["font.family"] = candidate
            break
    plt.rcParams["axes.unicode_minus"] = False  # 한글 폰트의 마이너스 글리프 깨짐 방지


_use_korean_font()

API = "https://stablecoins.llama.fi/stablecoincharts/all"
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUT_DIR = ROOT / "output"
CACHE_MAX_AGE_H = 12


@dataclass(frozen=True)
class Coin:
    key: str
    llama_id: int
    label: str
    color: str  # dataviz 카테고리 팔레트 슬롯 1/2/3 (light)


# 슬롯 순서 고정 — 색은 순위가 아니라 자산에 귀속된다(시리즈가 빠져도 색은 그대로)
COINS: dict[str, Coin] = {
    "usdc": Coin("usdc", 2, "USDC", "#2a78d6"),   # slot 1 blue
    "eurc": Coin("eurc", 50, "EURC", "#eb6834"),  # slot 2 orange
    "usyc": Coin("usyc", 237, "USYC", "#1baf7a"), # slot 3 aqua
}

INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#8a8985"
SURFACE = "#fcfcfb"
GRID = "#e6e5e1"


# ---------------------------------------------------------------- 데이터 수집

def fetch_series(coin: Coin, refresh: bool = False) -> list[tuple[datetime, float]]:
    """(날짜, USD 환산 유통량) 시계열을 반환한다. 응답은 data/ 에 캐시한다."""
    cache = DATA_DIR / f"{coin.key}.json"
    fresh = cache.exists() and (time.time() - cache.stat().st_mtime) < CACHE_MAX_AGE_H * 3600

    if fresh and not refresh:
        raw = json.loads(cache.read_text())
    else:
        resp = requests.get(API, params={"stablecoin": coin.llama_id}, timeout=30)
        resp.raise_for_status()
        raw = resp.json()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(raw))

    series: list[tuple[datetime, float]] = []
    for row in raw:
        # EURC는 peggedEUR, USDC/USYC는 peggedUSD — 키를 고정하지 않고 USD 환산값을 집는다
        usd = row.get("totalCirculatingUSD") or {}
        value = next((v for v in usd.values() if isinstance(v, (int, float))), None)
        if not value:
            continue
        series.append((datetime.fromtimestamp(int(row["date"]), tz=timezone.utc), float(value)))
    series.sort(key=lambda p: p[0])
    return series


def clip(series, start: datetime | None, end: datetime | None):
    return [(d, v) for d, v in series
            if (start is None or d >= start) and (end is None or d <= end)]


# ------------------------------------------------------------------- 차트

def unit_for(peak: float) -> tuple[float, str]:
    """축 전체에 쓸 단위를 봉우리 값 기준으로 하나만 고른다."""
    if peak >= 1e9:
        return 1e9, "B"
    if peak >= 1e6:
        return 1e6, "M"
    if peak >= 1e3:
        return 1e3, "K"
    return 1.0, ""


def human(value: float) -> str:
    div, suffix = unit_for(value)
    scaled = value / div
    return f"${scaled:,.0f}{suffix}" if scaled >= 10 else f"${scaled:,.1f}{suffix}"


def tex_safe(text: str) -> str:
    """matplotlib이 $...$ 를 수식으로 파싱하는 걸 막는다 (금액이 두 번 이상 들어가는 문자열용)."""
    return text.replace("$", r"\$")


def _style_axes(ax) -> None:
    """격자와 축선은 뒤로 물리고, 데이터가 앞에 오게 한다."""
    ax.set_facecolor(SURFACE)
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK_SECONDARY, labelsize=9.5, length=0)
    ax.margins(x=0.0)


def _time_axis(ax) -> None:
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=(4, 7, 10)))


def _draw_line(ax, key: str, series: list, label_last: bool = True) -> None:
    coin = COINS[key]
    xs = [d for d, _ in series]
    ys = [v for _, v in series]
    ax.plot(xs, ys, color=coin.color, linewidth=2, solid_capstyle="round",
            label=coin.label, zorder=3)
    if label_last:
        # 직접 라벨 — 색만으로 식별하지 않게 하고, 대비가 낮은 색의 판독성을 보완한다
        ax.annotate(tex_safe(f"  {coin.label}  {human(ys[-1])}"),
                    xy=(xs[-1], ys[-1]), xytext=(6, 0), textcoords="offset points",
                    va="center", ha="left", fontsize=9.5, color=INK_PRIMARY, zorder=4)


def _credit(fig, datasets: dict[str, list]) -> None:
    last = max(s[-1][0] for s in datasets.values() if s)
    fig.text(0.10, 0.015, f"출처: DefiLlama Stablecoins API · {last:%Y-%m-%d} 기준",
             fontsize=8.5, color=INK_MUTED)


def plot_overlay(datasets: dict[str, list], scale: str, out_path: Path) -> Path:
    """한 축에 겹쳐 그린다. 규모가 비슷한 시리즈 또는 단일 시리즈용."""
    fig, ax = plt.subplots(figsize=(12, 6.4), dpi=160)
    fig.patch.set_facecolor(SURFACE)
    _style_axes(ax)
    _time_axis(ax)

    for key, series in datasets.items():
        _draw_line(ax, key, series)

    ax.set_yscale(scale)
    peak = max(v for s in datasets.values() for _, v in s)
    div, suffix = unit_for(peak)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"${v / div:,.0f}{suffix}"))
    ax.set_ylim(bottom=0 if scale == "linear" else None)

    names = " · ".join(COINS[k].label for k in datasets)
    note = " (로그 스케일)" if scale == "log" else ""
    ax.set_title(f"Circle 발행 코인 유통량 — {names}", fontsize=15, color=INK_PRIMARY,
                 fontweight="bold", loc="left", pad=16)
    ax.set_ylabel(f"유통량 (USD 환산){note}", fontsize=10, color=INK_SECONDARY, labelpad=10)

    if len(datasets) > 1:
        leg = ax.legend(loc="upper left", frameon=False, fontsize=9.5, ncol=len(datasets))
        for text in leg.get_texts():
            text.set_color(INK_SECONDARY)

    _credit(fig, datasets)
    fig.subplots_adjust(left=0.10, right=0.86, top=0.88, bottom=0.11)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=SURFACE)
    plt.close(fig)
    return out_path


def plot_facets(datasets: dict[str, list], out_path: Path) -> Path:
    """규모가 제각각인 시리즈는 축을 나눠 그린다.

    한 축에 몰아넣으면 작은 시리즈가 바닥에 깔리고, 로그로 피하면 큰 시리즈의
    실제 등락이 뭉개진다. 시간축만 공유하고 y축은 각자 갖게 한다.
    """
    n = len(datasets)
    fig, axes = plt.subplots(n, 1, figsize=(12, 2.5 * n + 1.4), dpi=160, sharex=True)
    axes = [axes] if n == 1 else list(axes)
    fig.patch.set_facecolor(SURFACE)

    for ax, (key, series) in zip(axes, datasets.items()):
        coin = COINS[key]
        _style_axes(ax)
        _draw_line(ax, key, series, label_last=False)
        ax.fill_between([d for d, _ in series], [v for _, v in series],
                        color=coin.color, alpha=0.10, linewidth=0, zorder=2)

        peak = max(v for _, v in series)
        div, suffix = unit_for(peak)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _, d=div, s=suffix: f"${v / d:,.0f}{s}"))
        ax.set_ylim(0, peak * 1.18)

        latest = series[-1][1]
        ax.annotate(tex_safe(f"{coin.label}   현재 {human(latest)}   최고 {human(peak)}"),
                    xy=(0.0, 1.0), xycoords="axes fraction", xytext=(0, 8),
                    textcoords="offset points", fontsize=11, fontweight="bold",
                    color=INK_PRIMARY, va="bottom", ha="left")
        # 색 식별을 돕는 표식 — 텍스트는 잉크색을 유지한다
        ax.annotate("●", xy=(1.0, 1.0), xycoords="axes fraction", xytext=(-2, 9),
                    textcoords="offset points", fontsize=11, color=coin.color,
                    va="bottom", ha="right")

    _time_axis(axes[-1])
    fig.suptitle("Circle 발행 코인 유통량", fontsize=15, color=INK_PRIMARY,
                 fontweight="bold", x=0.10, ha="left", y=0.985)
    fig.supylabel("유통량 (USD 환산)", fontsize=10, color=INK_SECONDARY, x=0.022)

    _credit(fig, datasets)
    fig.subplots_adjust(left=0.10, right=0.97, top=0.90, bottom=0.075, hspace=0.42)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=SURFACE)
    plt.close(fig)
    return out_path


# -------------------------------------------------------------------- CLI

def parse_date(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def choose_layout(datasets: dict[str, list]) -> str:
    """규모 차이가 5배를 넘으면 축을 나눈다."""
    peaks = [max(v for _, v in s) for s in datasets.values() if s]
    if len(peaks) < 2:
        return "overlay"
    return "facet" if max(peaks) / min(peaks) > 5 else "overlay"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Circle 발행 코인 유통량 차트")
    p.add_argument("--coins", default="usdc,eurc,usyc",
                   help="쉼표 구분 (기본: usdc,eurc,usyc)")
    p.add_argument("--start", type=parse_date, help="시작일 YYYY-MM-DD")
    p.add_argument("--end", type=parse_date, help="종료일 YYYY-MM-DD")
    p.add_argument("--layout", choices=("auto", "facet", "overlay"), default="auto",
                   help="facet=코인별 분할, overlay=한 축에 겹침 (기본: auto)")
    p.add_argument("--scale", choices=("linear", "log"), default="linear",
                   help="overlay 레이아웃에만 적용 (기본: linear)")
    p.add_argument("--refresh", action="store_true", help="캐시 무시하고 API 재호출")
    p.add_argument("--out", type=Path, help="저장 경로 (기본: output/circle_supply.png)")
    args = p.parse_args(argv)

    keys = [k.strip().lower() for k in args.coins.split(",") if k.strip()]
    unknown = [k for k in keys if k not in COINS]
    if unknown:
        p.error(f"알 수 없는 코인: {', '.join(unknown)} (가능: {', '.join(COINS)})")

    datasets: dict[str, list] = {}
    for key in keys:
        series = clip(fetch_series(COINS[key], refresh=args.refresh), args.start, args.end)
        if not series:
            print(f"  ! {COINS[key].label}: 해당 기간 데이터 없음 — 건너뜀", file=sys.stderr)
            continue
        datasets[key] = series
        first, last = series[0], series[-1]
        print(f"  {COINS[key].label:5} {len(series):5,}일  "
              f"{first[0]:%Y-%m-%d} {human(first[1]):>9}  ->  "
              f"{last[0]:%Y-%m-%d} {human(last[1]):>9}")

    if not datasets:
        print("데이터가 없습니다.", file=sys.stderr)
        return 1

    layout = choose_layout(datasets) if args.layout == "auto" else args.layout
    out = args.out or (OUT_DIR / "circle_supply.png")
    if layout == "facet":
        plot_facets(datasets, out)
    else:
        plot_overlay(datasets, args.scale, out)

    print(f"\n레이아웃: {layout}\n저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
