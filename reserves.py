#!/usr/bin/env python3
"""USDC 준비금(BlackRock Circle Reserve Fund, USDXX)의 만기 구조를 그린다.

Circle 매출은 준비금 운용수익이고, 그 수익이 금리 변화를 얼마나 빨리 따라가는지는
만기 구조가 결정한다. 만기가 짧을수록 가격 위험은 0에 가깝지만 이자수익은 금리에
그대로 연동된다. 이 스크립트는 그 구조를 두 패널로 보여준다.

  위  : 만기일별 보유액 (국채 직접 보유 vs 국채 레포)
  아래: 누적 상환 비율 — 며칠 만에 몇 %가 현금화되는가

데이터 출처: BlackRock이 매일 공시하는 USDXX 보유내역 (CUSIP은 미제공)

사용 예:
  python reserves.py
  python reserves.py --refresh
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import timedelta

import matplotlib.pyplot as plt
import matplotlib.dates as mdates

import circle_data as cd


def summarize(as_of, holdings):
    total = sum(h.market_value for h in holdings)
    repo = sum(h.market_value for h in holdings if h.is_repo)
    wam = sum(h.market_value * (h.maturity - as_of).days for h in holdings) / total
    return total, repo, total - repo, wam


def by_maturity(holdings):
    """만기일 -> (레포 금액, 국채 금액)"""
    buckets = defaultdict(lambda: [0.0, 0.0])
    for h in holdings:
        buckets[h.maturity][0 if h.is_repo else 1] += h.market_value
    return dict(sorted(buckets.items()))


def plot(as_of, holdings, out_path):
    """세 패널로 나눈다.

    레포 하나가 68%라 국채 사다리와 같은 축에 놓으면 사다리가 뭉개진다.
    구성비는 구성비대로, 만기 분포는 국채만 따로, 상환 속도는 전체 기준으로 본다.
    """
    total, repo, bills, wam = summarize(as_of, holdings)
    bill_buckets = by_maturity([h for h in holdings if not h.is_repo])
    all_buckets = by_maturity(holdings)

    fig, (ax_mix, ax_bar, ax_cum) = plt.subplots(
        3, 1, figsize=(12, 9.4), dpi=160,
        gridspec_kw={"height_ratios": [0.32, 1.25, 1.0]})
    fig.patch.set_facecolor(cd.SURFACE)

    # --- 1) 자산 유형 구성 ----------------------------------------------
    repo_pct, bill_pct = repo / total * 100, bills / total * 100
    ax_mix.barh([0], [repo_pct], color=cd.REPO_COLOR, height=0.5, zorder=3)
    # 2px 상당의 표면색 간격 — 인접한 두 채움이 붙어 보이지 않게 한다
    ax_mix.barh([0], [bill_pct], left=[repo_pct + 0.3], color=cd.BILL_COLOR,
                height=0.5, zorder=3)
    ax_mix.set_xlim(0, 100)
    ax_mix.set_ylim(-0.6, 0.9)
    ax_mix.axis("off")
    ax_mix.annotate(f"국채 레포 (익일물)  {repo_pct:.1f}%", xy=(repo_pct / 2, 0),
                    ha="center", va="center", fontsize=10, color="#ffffff",
                    fontweight="bold", zorder=4)
    ax_mix.annotate(f"국채 직접 보유  {bill_pct:.1f}%",
                    xy=(repo_pct + bill_pct / 2, 0), ha="center", va="center",
                    fontsize=10, color="#ffffff", fontweight="bold", zorder=4)

    # --- 2) 국채 만기 사다리 --------------------------------------------
    cd.style_axes(ax_bar)
    dates = list(bill_buckets)
    vals = [sum(bill_buckets[d]) for d in dates]
    ax_bar.bar(dates, vals, width=1.8, color=cd.BILL_COLOR, zorder=3)
    peak = max(vals)
    ax_bar.yaxis.set_major_formatter(cd.money_formatter(peak))
    ax_bar.set_ylim(0, peak * 1.28)
    ax_bar.set_ylabel("보유액", fontsize=10, color=cd.INK_SECONDARY, labelpad=10)
    ax_bar.annotate(cd.tex_safe(f"국채 직접 보유 {len(dates)}종  ·  합계 {cd.human(bills)}"
                                f"  (레포 {cd.human(repo)}는 전량 익일물이라 제외)"),
                    xy=(0.0, 1.0), xycoords="axes fraction", xytext=(0, 8),
                    textcoords="offset points", fontsize=9.5,
                    color=cd.INK_SECONDARY, va="bottom", ha="left")
    # 가장 큰 만기 두 건만 직접 라벨 — 모든 막대에 숫자를 달지 않는다
    for i in sorted(range(len(vals)), key=lambda i: -vals[i])[:2]:
        ax_bar.annotate(cd.tex_safe(cd.human(vals[i])), xy=(dates[i], vals[i]),
                        xytext=(0, 5), textcoords="offset points", fontsize=9,
                        color=cd.INK_PRIMARY, ha="center", va="bottom", zorder=4)

    # --- 3) 누적 상환 비율 (레포 포함 전체) -----------------------------
    cd.style_axes(ax_cum)
    xs, ys, run = [as_of], [0.0], 0.0
    for day in all_buckets:
        run += sum(all_buckets[day])
        xs.append(day)
        ys.append(run / total * 100)
    ax_cum.step(xs, ys, where="post", color=cd.RATE_COLOR, linewidth=2, zorder=3)
    ax_cum.fill_between(xs, ys, step="post", color=cd.RATE_COLOR,
                        alpha=0.10, linewidth=0, zorder=2)
    ax_cum.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax_cum.set_ylim(0, 112)
    ax_cum.set_ylabel("누적 상환 비율", fontsize=10, color=cd.INK_SECONDARY, labelpad=10)
    ax_cum.annotate("전체 준비금이 현금으로 돌아오는 속도 (레포 포함)",
                    xy=(0.0, 1.0), xycoords="axes fraction", xytext=(0, 8),
                    textcoords="offset points", fontsize=9.5,
                    color=cd.INK_SECONDARY, va="bottom", ha="left")

    day1 = next((y for x, y in zip(xs, ys) if (x - as_of).days <= 1 and y > 0), 0.0)
    ax_cum.annotate(f"하루 만에 {day1:.0f}%",
                    xy=(as_of + timedelta(days=1), day1), xytext=(12, -6),
                    textcoords="offset points", fontsize=9.5,
                    color=cd.INK_PRIMARY, va="top", ha="left", zorder=4)
    ax_cum.annotate(f"  {ys[-1]:.0f}%", xy=(xs[-1], ys[-1]), xytext=(6, 0),
                    textcoords="offset points", va="center", ha="left",
                    fontsize=9.5, color=cd.INK_PRIMARY, zorder=4)

    for ax in (ax_bar, ax_cum):
        ax.set_xlim(as_of - timedelta(days=2), max(all_buckets) + timedelta(days=3))
        ax.xaxis.set_major_locator(mdates.MonthLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax.xaxis.set_minor_locator(mdates.WeekdayLocator(byweekday=0))

    fig.suptitle("USDC 준비금 구성과 만기 구조 — Circle Reserve Fund (USDXX)",
                 fontsize=15, color=cd.INK_PRIMARY, fontweight="bold",
                 x=0.10, ha="left", y=0.978)
    fig.text(0.10, 0.932,
             cd.tex_safe(f"총 {cd.human(total)}  ·  가중평균만기 {wam:.0f}일  ·  "
                         f"최장 만기 {(max(all_buckets) - as_of).days}일"),
             fontsize=10.5, color=cd.INK_SECONDARY)
    cd.credit(fig, as_of, "BlackRock USDXX 일별 보유내역")

    fig.subplots_adjust(left=0.10, right=0.88, top=0.895, bottom=0.075, hspace=0.34)
    cd.OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=cd.SURFACE)
    plt.close(fig)
    return out_path


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="USDC 준비금 만기 구조 차트")
    p.add_argument("--refresh", action="store_true", help="캐시 무시하고 재수집")
    p.add_argument("--out", type=str, help="저장 경로")
    args = p.parse_args(argv)

    as_of, holdings = cd.fetch_reserves(args.refresh)
    total, repo, bills, wam = summarize(as_of, holdings)
    print(f"  기준일 {as_of:%Y-%m-%d}  포지션 {len(holdings)}개")
    print(f"  총 {cd.human(total)}  가중평균만기 {wam:.1f}일")
    print(f"    국채 레포      {cd.human(repo):>8}  {repo / total * 100:5.1f}%")
    print(f"    국채 직접 보유 {cd.human(bills):>8}  {bills / total * 100:5.1f}%")

    out = args.out or (cd.OUT_DIR / "reserves.png")
    plot(as_of, holdings, out)
    print(f"\n저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
