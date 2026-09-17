#!/usr/bin/env python3
"""데이터 수집과 차트 스타일 공용 모듈.

데이터 출처
  - DefiLlama Stablecoins API : Circle 발행 코인 유통량 (무료, 인증 불필요)
  - FRED DFF                  : 미 연방기금 실효금리 일별 (무료, 인증 불필요)
"""

from __future__ import annotations

import csv
import io
import json
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

LLAMA_API = "https://stablecoins.llama.fi/stablecoincharts/all"
LLAMA_ALL_API = "https://stablecoins.llama.fi/stablecoincharts/all"
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
# USDC 준비금의 대부분을 담고 있는 BlackRock Circle Reserve Fund(USDXX)의 일별 보유내역
USDXX_CSV = ("https://www.blackrock.com/cash/en-us/products/329365/circle-reserve-fund"
             "/1464253357814.ajax")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUT_DIR = ROOT / "output"
CACHE_MAX_AGE_H = 12

# --- 색: dataviz 카테고리 팔레트(light). 색은 순위가 아니라 자산에 귀속된다 -------
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#8a8985"
SURFACE = "#fcfcfb"
GRID = "#e6e5e1"

RATE_COLOR = "#4a3aa7"    # slot 7 violet — 정책금리
BILL_COLOR = "#2a78d6"    # slot 1 blue   — 국채 직접 보유
REPO_COLOR = "#eb6834"    # slot 2 orange — 국채 레포
HIKE_TINT = "#e34948"     # slot 8 red    — 인상기 배경
CUT_TINT = "#2a78d6"      # slot 1 blue   — 인하기 배경

Series = list[tuple[datetime, float]]


@dataclass(frozen=True)
class Coin:
    key: str
    llama_id: int
    label: str
    color: str


COINS: dict[str, Coin] = {
    "usdc": Coin("usdc", 2, "USDC", "#2a78d6"),   # slot 1 blue
    "eurc": Coin("eurc", 50, "EURC", "#eb6834"),  # slot 2 orange
    "usyc": Coin("usyc", 237, "USYC", "#1baf7a"), # slot 3 aqua
}

# Circle 발행 코인은 아니지만 대조군으로 쓰는 계열
REFERENCE: dict[str, Coin] = {
    "usdt": Coin("usdt", 1, "USDT", "#eb6834"),   # slot 2 orange
}


def use_korean_font() -> None:
    """한글 라벨이 두부(□)로 깨지지 않도록 사용 가능한 한글 폰트를 잡는다."""
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for candidate in ("Apple SD Gothic Neo", "Malgun Gothic", "NanumGothic",
                      "Noto Sans KR", "AppleGothic", "Arial Unicode MS"):
        if candidate in installed:
            plt.rcParams["font.family"] = candidate
            break
    plt.rcParams["axes.unicode_minus"] = False  # 한글 폰트의 마이너스 글리프 깨짐 방지


use_korean_font()


# ------------------------------------------------------------------ 수집

def _cached(name: str, fetch, refresh: bool = False, binary_text: bool = False):
    """응답을 data/ 에 캐시한다. CACHE_MAX_AGE_H 지나면 자동 갱신."""
    suffix = "txt" if binary_text else "json"
    cache = DATA_DIR / f"{name}.{suffix}"
    fresh = cache.exists() and (time.time() - cache.stat().st_mtime) < CACHE_MAX_AGE_H * 3600
    if fresh and not refresh:
        return cache.read_text() if binary_text else json.loads(cache.read_text())

    payload = fetch()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(payload if binary_text else json.dumps(payload))
    return payload


def fetch_supply(coin: Coin, refresh: bool = False) -> Series:
    """(날짜, USD 환산 유통량) 시계열."""
    def go():
        r = requests.get(LLAMA_API, params={"stablecoin": coin.llama_id}, timeout=30)
        r.raise_for_status()
        return r.json()

    out: Series = []
    for row in _cached(coin.key, go, refresh):
        # EURC는 peggedEUR, USDC/USYC는 peggedUSD — 키를 고정하지 않고 USD 환산값을 집는다
        usd = row.get("totalCirculatingUSD") or {}
        value = next((v for v in usd.values() if isinstance(v, (int, float))), None)
        if not value:
            continue
        out.append((datetime.fromtimestamp(int(row["date"]), tz=timezone.utc), float(value)))
    out.sort(key=lambda p: p[0])
    return out


def fetch_fed_funds(refresh: bool = False) -> Series:
    """(날짜, 연방기금 실효금리 %) 일별 시계열. FRED DFF."""
    def go():
        r = requests.get(FRED_CSV, params={"id": "DFF"}, timeout=30)
        r.raise_for_status()
        return r.text

    out: Series = []
    for row in csv.DictReader(io.StringIO(_cached("fedfunds_dff", go, refresh, binary_text=True))):
        raw = (row.get("DFF") or "").strip()
        if raw in ("", "."):  # FRED는 결측을 '.' 으로 준다
            continue
        out.append((datetime.strptime(row["observation_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc),
                    float(raw)))
    out.sort(key=lambda p: p[0])
    return out


def clip(series: Series, start: datetime | None, end: datetime | None) -> Series:
    return [(d, v) for d, v in series
            if (start is None or d >= start) and (end is None or d <= end)]


# ------------------------------------------------------------------ 표기

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
    """matplotlib이 $...$ 를 수식으로 파싱하는 걸 막는다."""
    return text.replace("$", r"\$")


# ------------------------------------------------------------------ 스타일

def style_axes(ax) -> None:
    """격자와 축선은 뒤로 물리고, 데이터가 앞에 오게 한다."""
    ax.set_facecolor(SURFACE)
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK_SECONDARY, labelsize=9.5, length=0)
    ax.margins(x=0.0)


def time_axis(ax) -> None:
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=(4, 7, 10)))


def money_formatter(peak: float):
    """축 눈금 포맷. 범위가 좁으면 소수 한 자리를 써서 눈금이 중복되지 않게 한다."""
    div, suffix = unit_for(peak)
    prec = 0 if peak / div >= 10 else 1
    return plt.FuncFormatter(lambda v, _: f"${v / div:,.{prec}f}{suffix}")


def credit(fig, last: datetime, sources: str, x: float = 0.10) -> None:
    fig.text(x, 0.015, f"출처: {sources} · {last:%Y-%m-%d} 기준",
             fontsize=8.5, color=INK_MUTED)


def parse_date(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)


# --------------------------------------------------------- 준비금 (USDXX)

@dataclass(frozen=True)
class Holding:
    description: str
    asset_type: str       # 원문 그대로
    is_repo: bool
    market_value: float
    maturity: datetime


def fetch_reserves(refresh: bool = False) -> tuple[datetime, list[Holding]]:
    """(기준일, 보유내역) — BlackRock이 매일 공시하는 USDXX 포트폴리오.

    CUSIP 칼럼은 제공되지 않는다. 국채는 전부 'TREASURY BILL' 로만 표기되고
    만기일·액면·시장가치가 붙는다.
    """
    def go():
        r = requests.get(USDXX_CSV, timeout=30, headers={"User-Agent": UA},
                         params={"fileType": "csv", "fileName": "USDXX_holdings",
                                 "dataType": "fund"})
        r.raise_for_status()
        return r.text

    text = _cached("usdxx_holdings", go, refresh, binary_text=True)
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))

    as_of = None
    for row in rows:
        if row and row[0].startswith("Fund Holdings as of") and len(row) > 1:
            as_of = datetime.strptime(row[1].strip(), "%d-%b-%Y").replace(tzinfo=timezone.utc)
            break

    header = next(i for i, r in enumerate(rows) if r and r[0] == "Position Description")
    holdings: list[Holding] = []
    for row in rows[header + 1:]:
        if len(row) < 6 or not row[0].strip():
            continue
        asset_type = row[1].strip()
        holdings.append(Holding(
            description=row[0].strip(),
            asset_type=asset_type,
            is_repo="Repurchase" in asset_type,
            market_value=float(row[4].replace(",", "")),
            maturity=datetime.strptime(row[5].strip(), "%d-%b-%Y").replace(tzinfo=timezone.utc),
        ))
    if as_of is None:
        as_of = min(h.maturity for h in holdings)
    return as_of, holdings


def fetch_market(refresh: bool = False) -> Series:
    """전체 스테이블코인 시장 규모 (USD 페그 기준) — 점유율 분모."""
    def go():
        r = requests.get(LLAMA_ALL_API, timeout=30)
        r.raise_for_status()
        return r.json()

    out: Series = []
    for row in _cached("all_stablecoins", go, refresh):
        value = (row.get("totalCirculatingUSD") or {}).get("peggedUSD")
        if not value:
            continue
        out.append((datetime.fromtimestamp(int(row["date"]), tz=timezone.utc), float(value)))
    out.sort(key=lambda p: p[0])
    return out
