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
import os
import re
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

# SEC는 요청마다 연락처가 담긴 User-Agent를 요구한다. 환경변수로 본인 것을 넣을 것.
#   export SEC_USER_AGENT="이름 you@example.com"
SEC_UA = os.environ.get("SEC_USER_AGENT", "Circle-Revenue-Structure research@example.com")
SEC_CIK = "0001876042"  # Circle Internet Group, Inc.
SEC_SUBMISSIONS = f"https://data.sec.gov/submissions/CIK{SEC_CIK}.json"
SEC_CONCEPT = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json"
SEC_ARCHIVE = "https://www.sec.gov/Archives/edgar/data/1876042"

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


# ------------------------------------------------------------- 주가 · 주식수

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
TICKER = "CRCL"   # Circle Internet Group, 2025년 6월 상장


def fetch_price(ticker: str = TICKER, refresh: bool = False) -> Series:
    """(날짜, 종가) 일별 시계열."""
    def go():
        r = requests.get(YAHOO_CHART.format(ticker=ticker), timeout=30,
                         headers={"User-Agent": UA}, params={"range": "5y", "interval": "1d"})
        r.raise_for_status()
        return r.json()

    payload = _cached(f"price_{ticker.lower()}", go, refresh)
    result = payload["chart"]["result"][0]
    closes = result["indicators"]["quote"][0]["close"]
    out: Series = []
    for stamp, close in zip(result["timestamp"], closes):
        if close is None:
            continue   # 거래 정지일 등
        out.append((datetime.fromtimestamp(int(stamp), tz=timezone.utc), float(close)))
    out.sort(key=lambda p: p[0])
    return out


def fetch_shares_outstanding(refresh: bool = False) -> Series:
    """(공시일, 발행주식수) — 각 10-Q/10-K 표지의 시점 주식수, 클래스 합산.

    시가총액에는 기간 가중평균이 아니라 시점 주식수를 써야 한다. 상장 분기의
    가중평균은 상장 전 기간이 섞여 실제의 절반 이하로 나온다.
    """
    def go():
        recent = json.loads(_sec_get(SEC_SUBMISSIONS))["filings"]["recent"]
        out: dict[str, float] = {}
        for form, report, filed, accession in zip(
                recent["form"], recent["reportDate"], recent["filingDate"],
                recent["accessionNumber"]):
            if form not in ("10-Q", "10-K"):
                continue
            acc = accession.replace("-", "")
            doc = f"crcl-{report.replace('-', '')}"
            try:
                xml = _sec_get(f"{SEC_ARCHIVE}/{acc}/{doc}_htm.xml")
            except requests.HTTPError:
                continue
            # 표지에는 클래스별로 따로 실린다. 전부 더해야 총 발행주식수가 된다
            total = sum(float(m.group(1)) for m in re.finditer(
                r'<dei:EntityCommonStockSharesOutstanding[^>]*>([\d.]+)<', xml))
            if total:
                out[filed] = total
            time.sleep(0.4)
        return out

    raw = _cached("sec_shares_outstanding", go, refresh)
    return sorted((datetime.fromisoformat(k).replace(tzinfo=timezone.utc), v)
                  for k, v in raw.items())


def fetch_filing_dates(refresh: bool = False) -> dict[Quarter, datetime]:
    """분기별 10-Q/10-K 제출일. 실적이 시장에 공개된 시점의 근사값."""
    def go():
        recent = json.loads(_sec_get(SEC_SUBMISSIONS))["filings"]["recent"]
        return {report: filed for form, report, filed
                in zip(recent["form"], recent["reportDate"], recent["filingDate"])
                if form in ("10-Q", "10-K")}

    out = {}
    for report, filed in _cached("sec_filing_dates", go, refresh).items():
        end = datetime.fromisoformat(report).replace(tzinfo=timezone.utc)
        out[(end.year, (end.month - 1) // 3 + 1)] = \
            datetime.fromisoformat(filed).replace(tzinfo=timezone.utc)
    return out


# ------------------------------------------------------- 단기금리 (수익률 대리)

def fetch_short_rate(series_id: str = "DTB3", refresh: bool = False) -> Series:
    """FRED 금리 시계열. 기본값 DTB3(3개월 국채)는 준비금 수익률에 가장 가깝다."""
    def go():
        r = requests.get(FRED_CSV, params={"id": series_id}, timeout=30)
        r.raise_for_status()
        return r.text

    out: Series = []
    for row in csv.DictReader(io.StringIO(_cached(f"fred_{series_id}", go, refresh, True))):
        raw = (row.get(series_id) or "").strip()
        if raw in ("", "."):
            continue
        out.append((datetime.strptime(row["observation_date"], "%Y-%m-%d")
                    .replace(tzinfo=timezone.utc), float(raw)))
    out.sort(key=lambda p: p[0])
    return out


# ------------------------------------------------------------- SEC EDGAR

Quarter = tuple[int, int]


def quarter_of(day: datetime) -> Quarter:
    return day.year, (day.month - 1) // 3 + 1


def _sec_get(url: str) -> str:
    r = requests.get(url, timeout=40, headers={"User-Agent": SEC_UA})
    r.raise_for_status()
    return r.text


QUARTER_ENDS = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}


def _concept_periods(cache_key: str, tag: str, refresh: bool,
                     unit: str = "USD") -> dict[tuple[str, str], float]:
    """companyfacts의 표준 태그 하나를 (시작일, 종료일) -> 값 으로 정리한다."""
    def go():
        return json.loads(_sec_get(SEC_CONCEPT.format(cik=SEC_CIK, tag=tag)))

    out = {}
    for u in _cached(cache_key, go, refresh)["units"][unit]:
        if u.get("form") in ("10-Q", "10-K") and u.get("start"):
            out[(u["start"], u["end"])] = float(u["val"])
    return out


def annual_from_periods(periods: dict[tuple[str, str], float]) -> dict[int, float]:
    """연간(1월 1일~12월 31일) 값만 뽑는다. 분기 4개를 합치면 결측인 해가 빠진다."""
    return {int(start[:4]): value for (start, end), value in periods.items()
            if start.endswith("-01-01") and end.endswith("-12-31")}


def quarterly_from_periods(periods: dict[tuple[str, str], float],
                           derived: set | None = None,
                           subtract: bool = True) -> dict[Quarter, float]:
    """(시작일, 종료일) -> 값 을 분기 단독 값으로 정리한다.

    10-K는 분기를 따로 태깅하지 않고 연간만 싣는 경우가 많다. 그럴 때는
    연초부터의 누적 기간 둘을 빼서 해당 분기를 복원한다 (연간 - 9개월 = 4분기).
    """
    out: dict[Quarter, float] = {}
    for (start, end), value in periods.items():
        days = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days
        if 80 <= days <= 95:
            out[quarter_of(datetime.fromisoformat(start).replace(tzinfo=timezone.utc))] = value

    if not subtract:
        return out   # 가중평균처럼 차감이 성립하지 않는 지표

    cumulative = {(start[:4], end): v for (start, end), v in periods.items()
                  if start.endswith("-01-01")}
    for (year, end), value in cumulative.items():
        for q in (2, 3, 4):
            if end != f"{year}-{QUARTER_ENDS[q]}":
                continue
            prior = cumulative.get((year, f"{year}-{QUARTER_ENDS[q - 1]}"))
            key = (int(year), q)
            if prior is not None and key not in out:
                out[key] = value - prior
                if derived is not None:
                    derived.add(key)
    return out


def fetch_reported_revenue(refresh: bool = False,
                           derived: set | None = None) -> dict[Quarter, float]:
    """공시 총매출(준비금 수익 + 기타 매출), 분기 단위.

    companyfacts API의 표준 태그라 바로 받을 수 있다.
    """
    return quarterly_from_periods(
        _concept_periods("sec_revenues", "Revenues", refresh), derived)


def fetch_reserve_income(refresh: bool = False,
                        derived: set | None = None) -> dict[Quarter, float]:
    """공시 준비금 수익, 분기 단위.

    Circle 손익계산서의 "Reserve income" 줄. 표준 태그
    us-gaap:InterestAndDividendIncomeOperating 로 태깅돼 companyfacts에서 받는다.
    유통비용 계약이 걸리는 대상이 총매출이 아니라 이 항목이다.
    """
    return quarterly_from_periods(_reserve_periods(refresh), derived)


def _reserve_periods(refresh: bool = False) -> dict[tuple[str, str], float]:
    return _concept_periods("sec_reserve_income",
                            "InterestAndDividendIncomeOperating", refresh)


def fetch_annual_reserve_income(refresh: bool = False) -> dict[int, float]:
    return annual_from_periods(_reserve_periods(refresh))


def fetch_annual_distribution_costs(refresh: bool = False) -> dict[int, float]:
    return annual_from_periods(_distribution_periods(refresh))


def _parse_instance(xml: str, tags: tuple[str, ...]) -> dict[tuple[str, str], dict]:
    """XBRL 인스턴스에서 (시작일, 종료일) -> {태그: 값}. 세그먼트 분해분은 제외한다."""
    contexts = {}
    for m in re.finditer(r'<(?:\w+:)?context id="([^"]+)"(.*?)</(?:\w+:)?context>', xml, re.S):
        body = m.group(2)
        start = re.search(r'<(?:\w+:)?startDate>([\d-]+)<', body)
        end = re.search(r'<(?:\w+:)?endDate>([\d-]+)<', body)
        if start and end and not re.search(r'<(?:\w+:)?segment>', body):
            contexts[m.group(1)] = (start.group(1), end.group(1))

    found: dict[tuple[str, str], dict] = {}
    for tag in tags:
        for m in re.finditer(rf'<{tag}\b[^>]*contextRef="([^"]+)"[^>]*>([-\d.]+)</{tag}>', xml):
            ref = m.group(1)
            if ref in contexts:
                found.setdefault(contexts[ref], {})[tag.split(":")[-1]] = float(m.group(2))
    return found


def _parse_segmented(xml: str, tag: str) -> dict[tuple[str, str], dict[str, float]]:
    """(시작일, 종료일) -> {세그먼트 멤버: 값}. 분해 항목을 읽을 때 쓴다.

    _parse_instance 는 전체 합계만 보려고 세그먼트 컨텍스트를 버리지만,
    매출 분해처럼 멤버별 값이 필요한 경우에는 그쪽이 본체다.
    """
    contexts = {}
    for m in re.finditer(r'<(?:\w+:)?context id="([^"]+)"(.*?)</(?:\w+:)?context>', xml, re.S):
        body = m.group(2)
        start = re.search(r'<(?:\w+:)?startDate>([\d-]+)<', body)
        end = re.search(r'<(?:\w+:)?endDate>([\d-]+)<', body)
        members = re.findall(r'<(?:\w+:)?explicitMember[^>]*>([^<]+)<', body)
        if start and end and len(members) == 1:
            contexts[m.group(1)] = (start.group(1), end.group(1),
                                    members[0].split(":")[-1])

    found: dict[tuple[str, str], dict[str, float]] = {}
    for f in re.finditer(rf'<{tag}\b[^>]*contextRef="([^"]+)"[^>]*>([-\d.]+)</{tag}>', xml):
        ref = f.group(1)
        if ref in contexts:
            start, end, member = contexts[ref]
            found.setdefault((start, end), {})[member] = float(f.group(2))
    return found


# 기타 매출 분해에 쓰이는 세그먼트 멤버
OTHER_REVENUE_LABELS = {
    "SubscriptionAndServicesMember": "구독·서비스",
    "TransactionRevenueMember": "거래 수수료",
    "OtherServicesMember": "기타",
}


def fetch_other_revenue_mix(refresh: bool = False) -> dict[tuple[str, str], dict[str, float]]:
    """기타 매출의 구성 항목별 금액. 10-K/10-Q의 매출 분해 주석에서 읽는다."""
    def go():
        recent = json.loads(_sec_get(SEC_SUBMISSIONS))["filings"]["recent"]
        result: dict[str, dict[str, float]] = {}
        for form, report, accession in zip(recent["form"], recent["reportDate"],
                                           recent["accessionNumber"]):
            if form not in ("10-Q", "10-K"):
                continue
            acc = accession.replace("-", "")
            doc = f"crcl-{report.replace('-', '')}"
            try:
                xml = _sec_get(f"{SEC_ARCHIVE}/{acc}/{doc}_htm.xml")
            except requests.HTTPError:
                continue
            for period, members in _parse_segmented(
                    xml, "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax").items():
                picked = {k: v for k, v in members.items() if k in OTHER_REVENUE_LABELS}
                if picked:
                    result.setdefault(f"{period[0]}|{period[1]}", {}).update(picked)
            time.sleep(0.4)
        return result

    raw = _cached("sec_other_revenue_mix", go, refresh)
    return {tuple(k.split("|")): v for k, v in raw.items()}


def _distribution_periods(refresh: bool = False) -> dict[tuple[str, str], float]:
    """유통·거래비용의 (시작일, 종료일) -> 값. 분기·누적·연간을 모두 담는다."""
    def go():
        recent = json.loads(_sec_get(SEC_SUBMISSIONS))["filings"]["recent"]
        result: dict[str, float] = {}
        for form, report_date, accession in zip(recent["form"], recent["reportDate"],
                                                recent["accessionNumber"]):
            if form not in ("10-Q", "10-K"):
                continue
            acc = accession.replace("-", "")
            doc = f"crcl-{report_date.replace('-', '')}"
            try:
                xml = _sec_get(f"{SEC_ARCHIVE}/{acc}/{doc}_htm.xml")
            except requests.HTTPError:
                continue
            for (start, end), vals in _parse_instance(
                    xml, ("crcl:DistributionTransactionAndOtherCosts",)).items():
                result[f"{start}|{end}"] = vals["DistributionTransactionAndOtherCosts"]
            time.sleep(0.4)  # SEC 요청 간격
        return result

    raw = _cached("sec_distribution_costs_v2", go, refresh)
    return {tuple(k.split("|")): v for k, v in raw.items()}


def fetch_distribution_costs(refresh: bool = False,
                             derived: set | None = None) -> dict[Quarter, float]:
    """분기별 유통·거래비용.

    companyfacts API에는 없다. 회사 확장 태그(crcl:...)라서 각 10-Q/10-K의
    XBRL 인스턴스를 직접 받아 파싱해야 한다.
    """
    return quarterly_from_periods(_distribution_periods(refresh), derived)
