#!/usr/bin/env python3
"""Circle 매출 추정 모델 — 시장 데이터로 추정하고 공시로 검증한다.

    준비금 수익 = 분기 평균 USDC 발행잔액 x 단기금리 x 기간
    유통비용    = 매출 x 비율          (과거는 공시 실제값, 진행 분기는 가정)
    RLDC        = 매출 - 유통비용      (Circle이 실제로 갖는 몫)

준비금 수익은 시장 데이터만으로 오차 3% 안에서 재현된다. 반면 유통비용은
시장 데이터로 예측할 수 없다 — Coinbase는 자기 플랫폼에 올라온 USDC의 준비금
수익을 100%, 그 밖에서 발생한 수익을 50% 가져가는데, 그 플랫폼 내 잔액은
체인에 찍히지 않고 Circle 공시에만 나오기 때문이다. 그래서 과거 분기는 공시에서
읽어오고, 아직 공시가 없는 진행 중 분기만 최근 비율로 가정한다.

데이터 출처: DefiLlama · FRED · SEC EDGAR

사용 예:
  python revenue_model.py
  python revenue_model.py --rate-series SOFR
  python revenue_model.py --scenario
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
TRAILING_QUARTERS = 4         # 진행 분기 유통비용 비율을 뽑을 구간


@dataclass
class QuarterResult:
    quarter: cd.Quarter
    days: int
    complete: bool
    avg_aum: float
    avg_rate: float
    modeled: float
    reported: float | None
    distribution: float | None
    derived: bool                # 공시가 분기를 따로 싣지 않아 차감으로 복원한 값
    dist_ratio: float            # 실제값이 없으면 가정치
    dist_assumed: bool

    @property
    def revenue(self) -> float:
        """검증에는 공시값을, 진행 분기에는 모델값을 쓴다."""
        return self.reported if self.reported is not None else self.modeled

    @property
    def dist_amount(self) -> float:
        if self.distribution is not None:
            return self.distribution
        return self.revenue * self.dist_ratio

    @property
    def rldc(self) -> float:
        return self.revenue - self.dist_amount

    @property
    def error(self) -> float | None:
        if self.reported is None:
            return None
        return (self.modeled / self.reported - 1) * 100


def quarter_days(q: cd.Quarter) -> tuple[datetime, datetime]:
    year, quarter = q
    start = datetime(year, (quarter - 1) * 3 + 1, 1, tzinfo=timezone.utc)
    end = (datetime(year + 1, 1, 1, tzinfo=timezone.utc) if quarter == 4
           else datetime(year, quarter * 3 + 1, 1, tzinfo=timezone.utc))
    return start, end


def build(supply, rates, reported, distribution, derived=()) -> list[QuarterResult]:
    """derived: 차감으로 복원한 분기. 비율 가정의 기준에서는 제외한다."""
    by_q_supply, by_q_rate = {}, {}
    for day, value in supply:
        by_q_supply.setdefault(cd.quarter_of(day), []).append(value)
    for day, value in rates:
        by_q_rate.setdefault(cd.quarter_of(day), []).append(value)

    # 유통비용 비율: 공시가 있는 최근 분기들의 평균을 진행 분기에 적용한다
    known = sorted(q for q in distribution if q in reported and q not in derived)
    recent = known[-TRAILING_QUARTERS:]
    fallback = (sum(distribution[q] / reported[q] for q in recent) / len(recent)
                if recent else 0.0)

    results = []
    for q in sorted(by_q_supply):
        aum_days, rate_days = by_q_supply[q], by_q_rate.get(q, [])
        if not rate_days or len(aum_days) < 30:
            continue
        start, end = quarter_days(q)
        full = (end - start).days
        complete = len(aum_days) >= full - 3

        avg_aum = sum(aum_days) / len(aum_days)
        avg_rate = sum(rate_days) / len(rate_days)
        # 진행 중 분기는 현재 수준이 분기 끝까지 이어진다고 보고 분기 전체로 환산
        modeled = avg_aum * avg_rate / 100 * (full / 365)

        rep, dist = reported.get(q), distribution.get(q)
        results.append(QuarterResult(
            quarter=q, days=len(aum_days), complete=complete,
            avg_aum=avg_aum, avg_rate=avg_rate, modeled=modeled,
            reported=rep, distribution=dist, derived=q in derived,
            dist_ratio=(dist / rep) if (dist and rep) else fallback,
            dist_assumed=dist is None,
        ))
    return results


RATE_STEPS = (-0.50, -0.25, 0.0, 0.25, 0.50)
AUM_STEPS = (-0.10, 0.0, 0.10)


def scenario(latest: QuarterResult, rate_steps=RATE_STEPS, aum_steps=AUM_STEPS):
    """금리와 발행잔액을 흔들었을 때의 연간 매출과 RLDC.

    반환: {(금리변화, 잔액변화): (연간 매출, 연간 RLDC)}
    """
    grid = {}
    for d_rate in rate_steps:
        for d_aum in aum_steps:
            aum = latest.avg_aum * (1 + d_aum)
            rate = latest.avg_rate + d_rate
            revenue = aum * rate / 100          # 연간 기준
            grid[(d_rate, d_aum)] = (revenue, revenue * (1 - latest.dist_ratio))
    return grid


def print_scenario(latest: QuarterResult) -> None:
    grid = scenario(latest)
    q = f"{latest.quarter[0]}Q{latest.quarter[1]}"
    print(f"\n  시나리오 — {q} 기준 "
          f"(AUM {latest.avg_aum / 1e9:.1f}B, 금리 {latest.avg_rate:.2f}%, "
          f"유통비율 {latest.dist_ratio * 100:.1f}%), 연간 환산 · 단위 $M\n")

    for title, idx in (("연간 총매출", 0), ("연간 RLDC (Circle 몫)", 1)):
        print(f"  {title}")
        header = "".join(f"{f'AUM {d * 100:+.0f}%':>13}" for d in AUM_STEPS)
        print(f"    {'금리':<9}{header}")
        for d_rate in RATE_STEPS:
            cells = "".join(f"{grid[(d_rate, d_aum)][idx] / 1e6:12,.0f} "
                            for d_aum in AUM_STEPS)
            mark = "  <- 현재" if d_rate == 0 else ""
            print(f"    {d_rate:+.2f}p    {cells}{mark}")
        print()

    base = grid[(0.0, 0.0)]
    up = grid[(0.25, 0.0)]
    print(f"  금리 +25bp 단독 효과: 매출 {(up[0] - base[0]) / 1e6:+,.0f}M  ->  "
          f"Circle 몫 {(up[1] - base[1]) / 1e6:+,.0f}M "
          f"(차액 {(up[0] - base[0] - up[1] + base[1]) / 1e6:,.0f}M은 유통비용으로 유출)")


# --------------------------------------------------------------------- 차트

def plot(results, out_path):
    shown = [r for r in results if r.reported is not None or not r.complete]
    fig, (ax_rev, ax_err) = plt.subplots(
        2, 1, figsize=(12, 8.0), dpi=160, sharex=True,
        gridspec_kw={"height_ratios": [2.2, 1]})
    fig.patch.set_facecolor(cd.SURFACE)

    labels = [f"{q.quarter[0]}\nQ{q.quarter[1]}" for q in shown]
    xs = list(range(len(shown)))

    # --- 위: 매출 구성 + 모델 추정 --------------------------------------
    cd.style_axes(ax_rev)
    rldc = [r.rldc for r in shown]
    dist = [r.dist_amount for r in shown]
    # 공시가 없어 추정한 분기는 막대 전체를 해칭한다 — 색만으로 구분하지 않는다
    hatches = ["//" if r.reported is None else None for r in shown]

    for x, base, top, h in zip(xs, rldc, dist, hatches):
        ax_rev.bar([x], [base], width=0.62, color=RLDC_COLOR, hatch=h,
                   edgecolor=cd.SURFACE, linewidth=0 if h is None else 2, zorder=3)
        # 인접한 두 채움 사이에 2px 상당의 표면색 간격을 둔다
        ax_rev.bar([x], [top], width=0.62, bottom=[base], color=DIST_COLOR,
                   hatch=h, edgecolor=cd.SURFACE, linewidth=2, zorder=3)

    ax_rev.scatter(xs, [r.modeled for r in shown], s=44, color=MODEL_COLOR,
                   zorder=5, marker="D", edgecolor=cd.SURFACE, linewidth=1.5)

    peak = max(r.revenue for r in shown)
    ax_rev.set_ylim(0, peak * 1.30)
    ax_rev.yaxis.set_major_formatter(cd.money_formatter(peak))
    ax_rev.set_ylabel("분기 매출", fontsize=10, color=cd.INK_SECONDARY, labelpad=10)

    handles = [Patch(facecolor=RLDC_COLOR, label="RLDC (Circle 몫)"),
               Patch(facecolor=DIST_COLOR, label="유통비용 (주로 Coinbase)"),
               plt.Line2D([], [], marker="D", linestyle="none", markersize=7,
                          color=MODEL_COLOR, label="모델 추정 총매출")]
    leg = ax_rev.legend(handles=handles, loc="upper left", frameon=False,
                        fontsize=9.5, ncol=3)
    for text in leg.get_texts():
        text.set_color(cd.INK_SECONDARY)

    for x, r in zip(xs, shown):
        ax_rev.annotate(cd.tex_safe(cd.human(r.revenue)), xy=(x, r.revenue),
                        xytext=(0, 8), textcoords="offset points", fontsize=9,
                        color=cd.INK_PRIMARY, ha="center", va="bottom", zorder=6)
        if r.reported is None:
            ax_rev.annotate("추정", xy=(x, r.revenue), xytext=(0, 22),
                            textcoords="offset points", fontsize=8.5,
                            color=cd.INK_MUTED, ha="center", va="bottom", zorder=6)

    # --- 아래: 모델 오차 -------------------------------------------------
    cd.style_axes(ax_err)
    errs = [(x, r.error) for x, r in zip(xs, shown) if r.error is not None]
    ax_err.bar([x for x, _ in errs], [e for _, e in errs], width=0.62,
               color=MODEL_COLOR, zorder=3)
    ax_err.axhline(0, color=cd.GRID, linewidth=1, zorder=2)
    ax_err.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:+.0f}%"))
    span = max(abs(e) for _, e in errs) if errs else 5
    step = 2 if span <= 6 else 5
    limit = step * (int(span / step) + 1)
    ax_err.set_ylim(-limit * 1.6, limit)
    ax_err.set_yticks([t for t in range(-limit, limit + 1, step)])
    ax_err.set_ylabel("모델 오차", fontsize=10, color=cd.INK_SECONDARY, labelpad=10)
    ax_err.set_xticks(xs)
    ax_err.set_xticklabels(labels, fontsize=9.5, color=cd.INK_SECONDARY)
    if errs:
        mean_abs = sum(abs(e) for _, e in errs) / len(errs)
        ax_err.annotate(f"절대오차 평균 {mean_abs:.1f}%  ·  "
                        f"모델이 기타 매출을 빼고 계산해 일관되게 과소 추정한다",
                        xy=(0.0, 0.02), xycoords="axes fraction", xytext=(0, 0),
                        textcoords="offset points", fontsize=9,
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


# ----------------------------------------------------------------------- CLI

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Circle 매출 추정 모델")
    p.add_argument("--rate-series", default="DTB3",
                   help="FRED 금리 시계열 (기본: DTB3 = 3개월 국채)")
    p.add_argument("--scenario", action="store_true", help="금리/잔액 시나리오 표 출력")
    p.add_argument("--refresh", action="store_true", help="캐시 무시하고 재수집")
    p.add_argument("--out", type=str, help="저장 경로")
    args = p.parse_args(argv)

    supply = cd.fetch_supply(cd.COINS["usdc"], args.refresh)
    rates = cd.fetch_short_rate(args.rate_series, args.refresh)
    derived: set = set()
    reported = cd.fetch_reported_revenue(args.refresh, derived)
    distribution = cd.fetch_distribution_costs(args.refresh, derived)

    results = build(supply, rates, reported, distribution, derived)
    shown = [r for r in results if r.reported is not None or not r.complete]

    print(f"\n  금리 시계열: {args.rate_series}\n")
    print(f"  {'분기':7}{'평균 AUM':>11}{'금리':>7}{'모델':>10}{'공시':>10}"
          f"{'오차':>8}{'유통비용':>11}{'비중':>7}{'RLDC':>10}")
    for r in shown:
        q = f"{r.quarter[0]}Q{r.quarter[1]}"
        rep = cd.human(r.reported) if r.reported is not None else "—"
        err = f"{r.error:+.1f}%" if r.error is not None else "—"
        tail = ("  (진행 중, 유통비율 가정)" if r.dist_assumed
                else "  (연간-9개월 차감으로 복원)" if r.derived else "")
        print(f"  {q:7}{r.avg_aum / 1e9:9.1f}B{r.avg_rate:7.2f}"
              f"{cd.human(r.modeled):>10}{rep:>10}{err:>8}"
              f"{cd.human(r.dist_amount):>11}{r.dist_ratio * 100:6.1f}%"
              f"{cd.human(r.rldc):>10}{tail}")

    errors = [r.error for r in shown if r.error is not None]
    if errors:
        print(f"\n  절대오차 평균 {sum(abs(e) for e in errors) / len(errors):.1f}%"
              f"  ·  평균 편향 {sum(errors) / len(errors):+.1f}%")

    if args.scenario:
        print_scenario(shown[-1])

    out = args.out or (cd.OUT_DIR / "revenue_model.png")
    plot(results, out)
    print(f"\n저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
