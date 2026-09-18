#!/usr/bin/env python3
"""Circle 매출 추정 모델 — 시장 데이터로 추정하고 공시로 검증한다.

    준비금 수익 = 분기 평균 USDC 발행잔액 x 단기금리 x 기간
    유통비용    = 준비금 수익 x 비율   (과거는 공시 실제값, 진행 분기는 최근 평균)
    총매출      = 준비금 수익 + 기타 매출
    RLDC        = 총매출 - 유통비용   (Circle이 실제로 갖는 몫)

비율의 분모는 총매출이 아니라 **준비금 수익**이다. Coinbase 계약이 걸리는 대상이
준비금 수익이고, 기타 매출(구독·거래 수수료)은 나누지 않는 돈이기 때문이다.
기타 매출 비중이 2024년 0.9%에서 2026년 5%대로 커지는 중이라 분모를 총매출로
잡으면 비율이 갈수록 희석돼 보인다.

유통비용은 시장 데이터로 예측할 수 없다. Coinbase는 자기 플랫폼에 올라온 USDC의
준비금 수익을 배분받고(issuer retention 차감 후), 그 밖에서 발생한 수익은 다른
파트너 지급분을 뺀 나머지의 절반을 가져간다. 플랫폼 내 잔액은 체인에 찍히지 않고
Circle 공시에만 나온다. 그래서 과거 분기는 공시에서 읽고, 아직 공시가 없는 진행
중 분기만 최근 비율로 가정한다.

데이터 출처: DefiLlama · FRED · SEC EDGAR

사용 예:
  python revenue_model.py
  python revenue_model.py --scenario
  python revenue_model.py --rate-series SOFR
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone

import matplotlib.pyplot as plt
from matplotlib.patches import Patch

import circle_data as cd

MODEL_COLOR = cd.RATE_COLOR   # slot 7 violet — 모델 추정
RLDC_COLOR = "#2a78d6"        # slot 1 blue   — Circle 몫
DIST_COLOR = "#eb6834"        # slot 2 orange — 유통비용
TRAILING_QUARTERS = 4

# 공시에서 확인한 일회성 유통비용. 비율을 왜곡하므로 별도로 표시한다.
# 출처: Circle FY2025 10-K — "In November 2024, we entered into an agreement
# (the 'November Binance Agreement') with Binance... we paid Binance a
# $60.3 million one-time upfront fee"
ONE_OFF_COSTS: dict[cd.Quarter, tuple[float, str]] = {
    (2024, 4): (60.3e6, "Binance 일회성 선급금 (2024년 11월 계약)"),
}

RATE_STEPS = (-0.50, -0.25, 0.0, 0.25, 0.50)
AUM_STEPS = (-0.10, 0.0, 0.10)


@dataclass
class QuarterResult:
    quarter: cd.Quarter
    days: int
    avg_aum: float
    avg_rate: float
    modeled_ri: float                 # 모델이 추정한 준비금 수익
    reserve_income: float | None      # 공시 준비금 수익
    total_revenue: float | None       # 공시 총매출
    distribution: float | None        # 공시 유통·거래비용
    other_ratio: float                # 기타매출 / 준비금수익
    dist_ratio: float                 # 유통비용 / 준비금수익
    assumed: bool                     # 공시가 없어 가정한 분기
    derived: bool                     # 연간-누적 차감으로 복원한 분기
    complete: bool                    # 분기가 끝났는지 (마지막 분기 판별용)

    @property
    def ri(self) -> float:
        return self.reserve_income if self.reserve_income is not None else self.modeled_ri

    @property
    def revenue(self) -> float:
        if self.total_revenue is not None:
            return self.total_revenue
        return self.ri * (1 + self.other_ratio)

    @property
    def dist_amount(self) -> float:
        if self.distribution is not None:
            return self.distribution
        return self.ri * self.dist_ratio

    @property
    def rldc(self) -> float:
        return self.revenue - self.dist_amount

    @property
    def error(self) -> float | None:
        """모델은 준비금 수익을 추정하므로 그 항목과 대조한다."""
        if self.reserve_income is None:
            return None
        return (self.modeled_ri / self.reserve_income - 1) * 100

    @property
    def one_off(self) -> tuple[float, str] | None:
        return ONE_OFF_COSTS.get(self.quarter)

    @property
    def underlying_ratio(self) -> float:
        """일회성 항목을 뺀 경상 유통비용 비율 (준비금 수익 기준)."""
        amount = self.one_off[0] if self.one_off else 0.0
        return (self.dist_amount - amount) / self.ri


def quarter_bounds(q: cd.Quarter) -> tuple[datetime, datetime]:
    year, quarter = q
    start = datetime(year, (quarter - 1) * 3 + 1, 1, tzinfo=timezone.utc)
    end = (datetime(year + 1, 1, 1, tzinfo=timezone.utc) if quarter == 4
           else datetime(year, quarter * 3 + 1, 1, tzinfo=timezone.utc))
    return start, end


def _trailing(values: dict[cd.Quarter, float], skip: set) -> float:
    usable = sorted(q for q in values if q not in skip)[-TRAILING_QUARTERS:]
    return sum(values[q] for q in usable) / len(usable) if usable else 0.0


def build(supply, rates, reserve_income, revenue, distribution, derived=()) -> list[QuarterResult]:
    by_aum, by_rate = {}, {}
    for day, value in supply:
        by_aum.setdefault(cd.quarter_of(day), []).append(value)
    for day, value in rates:
        by_rate.setdefault(cd.quarter_of(day), []).append(value)

    # 진행 분기에 쓸 비율. 복원 분기와 일회성이 낀 분기는 기준에서 뺀다
    skip = set(derived) | set(ONE_OFF_COSTS)
    dist_ratios = {q: distribution[q] / reserve_income[q]
                   for q in distribution if q in reserve_income}
    other_ratios = {q: (revenue[q] - reserve_income[q]) / reserve_income[q]
                    for q in revenue if q in reserve_income}
    fallback_dist = _trailing(dist_ratios, skip)
    fallback_other = _trailing(other_ratios, skip)

    results = []
    for q in sorted(by_aum):
        aum_days, rate_days = by_aum[q], by_rate.get(q, [])
        if not rate_days or len(aum_days) < 30:
            continue
        start, end = quarter_bounds(q)
        full = (end - start).days
        avg_aum = sum(aum_days) / len(aum_days)
        avg_rate = sum(rate_days) / len(rate_days)
        # 진행 중 분기는 현재 수준이 분기 끝까지 이어진다고 보고 분기 전체로 환산
        results.append(QuarterResult(
            quarter=q, days=len(aum_days), avg_aum=avg_aum, avg_rate=avg_rate,
            modeled_ri=avg_aum * avg_rate / 100 * (full / 365),
            reserve_income=reserve_income.get(q), total_revenue=revenue.get(q),
            distribution=distribution.get(q),
            other_ratio=other_ratios.get(q, fallback_other),
            dist_ratio=dist_ratios.get(q, fallback_dist),
            assumed=q not in distribution, derived=q in derived,
            complete=len(aum_days) >= full - 3,
        ))
    return results


def visible(results: list[QuarterResult]) -> list[QuarterResult]:
    """공시가 있는 분기와, 아직 끝나지 않은 진행 분기만 남긴다.

    상장 전(2025년 6월 IPO) 분기는 공시가 없어 검증도 비교도 불가능하다.
    """
    return [r for r in results if r.reserve_income is not None or not r.complete]


def scenario(latest: QuarterResult):
    """금리와 발행잔액을 흔들었을 때의 연간 준비금 수익과 RLDC."""
    grid = {}
    for d_rate in RATE_STEPS:
        for d_aum in AUM_STEPS:
            ri = latest.avg_aum * (1 + d_aum) * (latest.avg_rate + d_rate) / 100
            revenue = ri * (1 + latest.other_ratio)
            grid[(d_rate, d_aum)] = (ri, revenue - ri * latest.dist_ratio)
    return grid


def print_scenario(latest: QuarterResult) -> None:
    grid = scenario(latest)
    q = f"{latest.quarter[0]}Q{latest.quarter[1]}"
    print(f"\n  시나리오 — {q} 기준 (AUM {latest.avg_aum / 1e9:.1f}B, "
          f"금리 {latest.avg_rate:.2f}%, 유통비율 {latest.dist_ratio * 100:.1f}%), "
          f"연간 환산 · 단위 $M\n")
    for title, idx in (("연간 준비금 수익", 0), ("연간 RLDC (Circle 몫)", 1)):
        print(f"  {title}")
        print(f"    {'금리':<9}" + "".join(f"{f'AUM {d * 100:+.0f}%':>13}" for d in AUM_STEPS))
        for d_rate in RATE_STEPS:
            cells = "".join(f"{grid[(d_rate, a)][idx] / 1e6:12,.0f} " for a in AUM_STEPS)
            print(f"    {d_rate:+.2f}p    {cells}" + ("  <- 현재" if d_rate == 0 else ""))
        print()
    base, up = grid[(0.0, 0.0)], grid[(0.25, 0.0)]
    leak = (up[0] - base[0]) - (up[1] - base[1])
    print(f"  금리 +25bp 단독 효과: 준비금 수익 {(up[0] - base[0]) / 1e6:+,.0f}M  ->  "
          f"Circle 몫 {(up[1] - base[1]) / 1e6:+,.0f}M "
          f"(차액 {leak / 1e6:,.0f}M은 유통비용으로 유출)")


def plot(results, out_path):
    shown = visible(results)
    fig, (ax_rev, ax_err) = plt.subplots(
        2, 1, figsize=(12, 8.0), dpi=160, sharex=True,
        gridspec_kw={"height_ratios": [2.2, 1]})
    fig.patch.set_facecolor(cd.SURFACE)

    xs = list(range(len(shown)))
    cd.style_axes(ax_rev)
    for x, r in zip(xs, shown):
        hatch = "//" if r.reserve_income is None else None
        ax_rev.bar([x], [r.rldc], width=0.62, color=RLDC_COLOR, hatch=hatch,
                   edgecolor=cd.SURFACE, linewidth=0 if hatch is None else 2, zorder=3)
        # 인접한 두 채움 사이에 2px 상당의 표면색 간격을 둔다
        ax_rev.bar([x], [r.dist_amount], width=0.62, bottom=[r.rldc], color=DIST_COLOR,
                   hatch=hatch, edgecolor=cd.SURFACE, linewidth=2, zorder=3)

    ax_rev.scatter(xs, [r.modeled_ri for r in shown], s=44, color=MODEL_COLOR,
                   zorder=5, marker="D", edgecolor=cd.SURFACE, linewidth=1.5)

    peak = max(r.revenue for r in shown)
    ax_rev.set_ylim(0, peak * 1.30)
    ax_rev.yaxis.set_major_formatter(cd.money_formatter(peak))
    ax_rev.set_ylabel("분기 매출", fontsize=10, color=cd.INK_SECONDARY, labelpad=10)

    handles = [Patch(facecolor=RLDC_COLOR, label="RLDC (Circle 몫)"),
               Patch(facecolor=DIST_COLOR, label="유통비용 (주로 Coinbase)"),
               plt.Line2D([], [], marker="D", linestyle="none", markersize=7,
                          color=MODEL_COLOR, label="모델 추정 준비금 수익")]
    leg = ax_rev.legend(handles=handles, loc="upper left", frameon=False,
                        fontsize=9.5, ncol=3)
    for text in leg.get_texts():
        text.set_color(cd.INK_SECONDARY)

    for x, r in zip(xs, shown):
        ax_rev.annotate(cd.tex_safe(cd.human(r.revenue)), xy=(x, r.revenue),
                        xytext=(0, 8), textcoords="offset points", fontsize=9,
                        color=cd.INK_PRIMARY, ha="center", va="bottom", zorder=6)
        if r.reserve_income is None:
            ax_rev.annotate("추정", xy=(x, r.revenue), xytext=(0, 22),
                            textcoords="offset points", fontsize=8.5,
                            color=cd.INK_MUTED, ha="center", va="bottom", zorder=6)
        if r.one_off:
            # 막대 폭 안에 들어가도록 짧게 — 상세는 표 각주에 있다
            ax_rev.annotate(f"일회성 {cd.human(r.one_off[0])}\n"
                            f"제외 시 {r.underlying_ratio * 100:.0f}%",
                            xy=(x, r.rldc + r.dist_amount / 2), fontsize=8.5,
                            color="#ffffff", fontweight="bold", ha="center",
                            va="center", linespacing=1.5, zorder=6)

    cd.style_axes(ax_err)
    errs = [(x, r.error) for x, r in zip(xs, shown) if r.error is not None]
    ax_err.bar([x for x, _ in errs], [e for _, e in errs], width=0.62,
               color=MODEL_COLOR, zorder=3)
    ax_err.axhline(0, color=cd.GRID, linewidth=1, zorder=2)
    ax_err.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:+.0f}%"))
    span = max(abs(e) for _, e in errs) if errs else 5
    step = 2 if span <= 6 else 5
    limit = step * (int(span / step) + 1)
    ax_err.set_ylim(-limit * 1.5, limit * 1.1)
    ax_err.set_yticks(list(range(-limit, limit + 1, step)))
    ax_err.set_ylabel("모델 오차", fontsize=10, color=cd.INK_SECONDARY, labelpad=10)
    ax_err.set_xticks(xs)
    ax_err.set_xticklabels([f"{r.quarter[0]}\nQ{r.quarter[1]}" for r in shown],
                           fontsize=9.5, color=cd.INK_SECONDARY)
    if errs:
        mean_abs = sum(abs(e) for _, e in errs) / len(errs)
        bias = sum(e for _, e in errs) / len(errs)
        ax_err.annotate(f"공시 준비금 수익 대비 · 절대오차 평균 {mean_abs:.1f}%  ·  "
                        f"편향 {bias:+.1f}%",
                        xy=(0.0, 0.02), xycoords="axes fraction", fontsize=9,
                        color=cd.INK_SECONDARY, va="bottom", ha="left")

    fig.suptitle("Circle 분기 매출 — 모델 추정 vs 공시 실적", fontsize=15,
                 color=cd.INK_PRIMARY, fontweight="bold", x=0.10, ha="left", y=0.975)
    cd.credit(fig, datetime.now(timezone.utc),
              "DefiLlama · FRED · SEC EDGAR (CIK 1876042)")
    fig.subplots_adjust(left=0.10, right=0.96, top=0.91, bottom=0.10, hspace=0.14)
    cd.OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=cd.SURFACE)
    plt.close(fig)
    return out_path


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Circle 매출 추정 모델")
    p.add_argument("--rate-series", default="DTB3",
                   help="FRED 금리 시계열 (기본: DTB3 = 3개월 국채)")
    p.add_argument("--scenario", action="store_true", help="금리/잔액 시나리오 표 출력")
    p.add_argument("--refresh", action="store_true", help="캐시 무시하고 재수집")
    p.add_argument("--out", type=str, help="저장 경로")
    args = p.parse_args(argv)

    derived: set = set()
    supply = cd.fetch_supply(cd.COINS["usdc"], args.refresh)
    rates = cd.fetch_short_rate(args.rate_series, args.refresh)
    reserve_income = cd.fetch_reserve_income(args.refresh, derived)
    revenue = cd.fetch_reported_revenue(args.refresh, derived)
    distribution = cd.fetch_distribution_costs(args.refresh, derived)

    results = build(supply, rates, reserve_income, revenue, distribution, derived)
    shown = visible(results)

    print(f"\n  금리 시계열: {args.rate_series}   ·   비율 분모: 준비금 수익\n")
    print(f"  {'분기':7}{'평균 AUM':>11}{'금리':>7}{'모델':>9}{'준비금수익':>12}"
          f"{'오차':>8}{'총매출':>10}{'유통비용':>10}{'비중':>7}{'RLDC':>10}")
    for r in shown:
        q = f"{r.quarter[0]}Q{r.quarter[1]}"
        ri = cd.human(r.reserve_income) if r.reserve_income is not None else "—"
        err = f"{r.error:+.1f}%" if r.error is not None else "—"
        tail = ("  (진행 중, 비율 가정)" if r.assumed
                else "  (차감으로 복원)" if r.derived else "")
        print(f"  {q:7}{r.avg_aum / 1e9:9.1f}B{r.avg_rate:7.2f}"
              f"{cd.human(r.modeled_ri):>9}{ri:>12}{err:>8}"
              f"{cd.human(r.revenue):>10}{cd.human(r.dist_amount):>10}"
              f"{r.dist_ratio * 100:6.1f}%{cd.human(r.rldc):>10}{tail}")

    for r in (x for x in shown if x.one_off):
        amount, note = r.one_off
        print(f"\n  * {r.quarter[0]}Q{r.quarter[1]} 유통비중 {r.dist_ratio * 100:.1f}%에는 "
              f"{note} {cd.human(amount)}이 포함돼 있다.\n"
              f"    이를 빼면 {r.underlying_ratio * 100:.1f}%로 인접 분기 수준이 된다.")

    errors = [r.error for r in shown if r.error is not None]
    if errors:
        print(f"\n  절대오차 평균 {sum(abs(e) for e in errors) / len(errors):.1f}%"
              f"  ·  편향 {sum(errors) / len(errors):+.1f}%")

    if args.scenario:
        print_scenario(shown[-1])

    out = args.out or (cd.OUT_DIR / "revenue_model.png")
    plot(results, out)
    print(f"\n저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
