#!/usr/bin/env python3
"""기타 매출(준비금 수익 외) 추이와 구성.

Circle 매출의 95% 안팎은 준비금 수익이고, 나머지가 기타 매출이다. 작지만
성격이 다르다 — 금리와 무관하고, 준비금 수익과 달리 Coinbase와 나누지 않는다.
그래서 이 항목이 커질수록 Circle이 실제로 갖는 몫의 비중이 올라간다.

매출 추정 모델(revenue_model.py)이 유일하게 과거 비율에 의존하는 부분이기도
하다. 준비금 수익은 잔액과 금리로 계산되지만 기타 매출은 그럴 수 없어서,
직전 4분기의 준비금 수익 대비 비율을 끌고 간다. 모델 오차가 남아 있다면
대부분 여기서 나온다.

  위    분기 기타 매출 (총매출 - 준비금 수익)
  가운데 준비금 수익 대비 비중
  아래  연간 구성 — 구독·서비스 / 거래 수수료 / 기타

데이터 출처: SEC EDGAR

사용 예:
  python other_revenue.py
  python other_revenue.py --consensus 769,786
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

import matplotlib.pyplot as plt
from matplotlib.patches import Patch

import circle_data as cd
from revenue_model import build, visible

TOTAL_COLOR = "#2a78d6"    # slot 1 blue
SHARE_COLOR = "#4a3aa7"    # slot 7 violet
MIX_COLORS = {
    "SubscriptionAndServicesMember": "#2a78d6",  # slot 1 blue
    "TransactionRevenueMember": "#eb6834",       # slot 2 orange
    "OtherServicesMember": "#1baf7a",            # slot 3 aqua
}
MIX_ORDER = list(MIX_COLORS)


def annual_mix(mix: dict) -> dict[int, dict[str, float]]:
    """연간(1월 1일~12월 31일) 구성만. 분기는 일부 항목이 태깅되지 않는다."""
    out = {}
    for (start, end), members in mix.items():
        if start.endswith("-01-01") and end.endswith("-12-31") and len(members) >= 2:
            out[int(start[:4])] = members
    return out


def plot(rows, mix, consensus, out_path):
    fig, (ax_amt, ax_share, ax_mix) = plt.subplots(
        3, 1, figsize=(11.5, 9.6), dpi=160,
        gridspec_kw={"height_ratios": [1.5, 1, 1.2]})
    fig.patch.set_facecolor(cd.SURFACE)

    xs = list(range(len(rows)))
    labels = [f"{r['q'][0]}\nQ{r['q'][1]}" for r in rows]

    # --- 위: 분기 기타 매출 ---------------------------------------------
    cd.style_axes(ax_amt)
    for x, r in zip(xs, rows):
        hatch = "//" if r["estimated"] else None
        ax_amt.bar([x], [r["other"]], width=0.6, color=TOTAL_COLOR, hatch=hatch,
                   edgecolor=cd.SURFACE, linewidth=0 if hatch is None else 2, zorder=3)
        ax_amt.annotate(cd.tex_safe(cd.human(r["other"])), xy=(x, r["other"]),
                        xytext=(0, 7), textcoords="offset points", fontsize=9,
                        color=cd.INK_PRIMARY, ha="center", va="bottom", zorder=5)

    peak = max([r["other"] for r in rows] + list(consensus.values() or [0]))
    ax_amt.set_ylim(0, peak * 1.34)
    ax_amt.yaxis.set_major_formatter(cd.money_formatter(peak))
    ax_amt.set_ylabel("분기 기타 매출", fontsize=10, color=cd.INK_SECONDARY, labelpad=10)
    ax_amt.set_xticks(xs)
    ax_amt.set_xticklabels(labels, fontsize=9, color=cd.INK_SECONDARY)

    # 컨센서스가 함의하는 수준 — 우리 모델의 준비금 수익을 빼서 역산한 값
    ax_amt.set_xlim(-0.7, len(rows) - 0.3)
    for name, value in consensus.items():
        ax_amt.axhline(value, color=cd.INK_MUTED, linewidth=1,
                       linestyle=(0, (4, 3)), zorder=2)
        # 막대가 없는 왼쪽 위 공간에 선 바로 위로 붙인다
        ax_amt.annotate(cd.tex_safe(f"{name} 함의 {cd.human(value)}"),
                        xy=(xs[0] - 0.55, value), xytext=(0, 4),
                        textcoords="offset points", fontsize=8.5,
                        color=cd.INK_SECONDARY, va="bottom", ha="left", zorder=5)
    if consensus:
        ax_amt.annotate("점선 = 시장 컨센서스 총매출에서 우리 모델의 준비금 수익을 뺀 값",
                        xy=(0.0, 1.0), xycoords="axes fraction", xytext=(0, 6),
                        textcoords="offset points", fontsize=9,
                        color=cd.INK_SECONDARY, va="bottom", ha="left")

    # --- 가운데: 준비금 수익 대비 비중 ----------------------------------
    cd.style_axes(ax_share)
    shares = [r["other"] / r["ri"] * 100 for r in rows]
    ax_share.plot(xs, shares, color=SHARE_COLOR, linewidth=2, marker="o",
                  markersize=8, markeredgecolor=cd.SURFACE, markeredgewidth=1.5, zorder=4)
    for x, v, r in zip(xs, shares, rows):
        ax_share.annotate(f"{v:.1f}%", xy=(x, v), xytext=(0, 10),
                          textcoords="offset points", fontsize=9,
                          color=cd.INK_MUTED if r["estimated"] else cd.INK_PRIMARY,
                          ha="center", va="bottom", zorder=5)
    ax_share.set_ylim(0, max(shares) * 1.38)
    ax_share.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax_share.set_ylabel("준비금 수익 대비", fontsize=10, color=cd.INK_SECONDARY, labelpad=10)
    ax_share.set_xticks(xs)
    ax_share.set_xticklabels(labels, fontsize=9, color=cd.INK_SECONDARY)

    # --- 아래: 연간 구성 ------------------------------------------------
    cd.style_axes(ax_mix)
    years = sorted(mix)
    ys = list(range(len(years)))
    bottoms = [0.0] * len(years)
    for member in MIX_ORDER:
        vals = [mix[y].get(member, 0.0) for y in years]
        ax_mix.bar(ys, vals, width=0.45, bottom=bottoms, color=MIX_COLORS[member],
                   edgecolor=cd.SURFACE, linewidth=2,
                   label=cd.OTHER_REVENUE_LABELS[member], zorder=3)
        bottoms = [b + v for b, v in zip(bottoms, vals)]
    for y, total in zip(ys, bottoms):
        ax_mix.annotate(cd.tex_safe(cd.human(total)), xy=(y, total), xytext=(0, 7),
                        textcoords="offset points", fontsize=9.5,
                        color=cd.INK_PRIMARY, ha="center", va="bottom", zorder=5)
    ax_mix.set_ylim(0, max(bottoms) * 1.30)
    ax_mix.yaxis.set_major_formatter(cd.money_formatter(max(bottoms)))
    ax_mix.set_ylabel("연간 기타 매출", fontsize=10, color=cd.INK_SECONDARY, labelpad=10)
    ax_mix.set_xticks(ys)
    ax_mix.set_xticklabels([str(y) for y in years], fontsize=10, color=cd.INK_SECONDARY)
    ax_mix.set_xlim(-0.7, len(years) - 0.3)
    handles = [Patch(facecolor=MIX_COLORS[m], label=cd.OTHER_REVENUE_LABELS[m])
               for m in MIX_ORDER]
    leg = ax_mix.legend(handles=handles, loc="upper left", frameon=False,
                        fontsize=9.5, ncol=3)
    for t in leg.get_texts():
        t.set_color(cd.INK_SECONDARY)

    fig.suptitle("Circle 기타 매출 — 추이와 구성", fontsize=15, color=cd.INK_PRIMARY,
                 fontweight="bold", x=0.10, ha="left", y=0.982)
    cd.credit(fig, datetime.now(timezone.utc), "SEC EDGAR (CIK 1876042)")
    fig.subplots_adjust(left=0.10, right=0.88, top=0.93, bottom=0.06, hspace=0.42)
    cd.OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=cd.SURFACE)
    plt.close(fig)
    return out_path


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="기타 매출 추이와 구성")
    p.add_argument("--consensus", default="769,786",
                   help="시장 컨센서스 총매출($M), 쉼표 구분. 빈 값이면 표시 안 함")
    p.add_argument("--refresh", action="store_true", help="캐시 무시하고 재수집")
    p.add_argument("--out", type=str, help="저장 경로")
    args = p.parse_args(argv)

    derived: set = set()
    results = visible(build(
        cd.fetch_supply(cd.COINS["usdc"], args.refresh),
        cd.fetch_short_rate("DTB3", args.refresh),
        cd.fetch_reserve_income(args.refresh, derived),
        cd.fetch_reported_revenue(args.refresh, derived),
        cd.fetch_distribution_costs(args.refresh, derived),
        derived))

    # 기타 매출 = 총매출 - 준비금 수익. 진행 분기는 둘 다 모델값이다
    rows = [dict(q=r.quarter, other=r.revenue - r.ri, ri=r.ri,
                 estimated=r.reserve_income is None) for r in results]

    latest_ri = rows[-1]["ri"]
    consensus = {}
    for token in (t.strip() for t in args.consensus.split(",") if t.strip()):
        consensus[f"컨센서스 ${token}M"] = float(token) * 1e6 - latest_ri

    print(f"\n  {'분기':7}{'기타 매출':>11}{'전분기비':>10}{'준비금 수익':>13}{'비중':>8}")
    for i, r in enumerate(rows):
        prev = rows[i - 1]["other"] if i else None
        qoq = f"{r['other'] / prev * 100 - 100:+.0f}%" if prev else "—"
        tail = "  (모델 추정)" if r["estimated"] else ""
        print(f"  {r['q'][0]}Q{r['q'][1]}{cd.human(r['other']):>11}{qoq:>10}"
              f"{cd.human(r['ri']):>13}{r['other'] / r['ri'] * 100:7.1f}%{tail}")

    mix = annual_mix(cd.fetch_other_revenue_mix(args.refresh))
    print(f"\n  연간 구성")
    for year in sorted(mix):
        parts = "  ".join(f"{cd.OTHER_REVENUE_LABELS[m]} {cd.human(mix[year][m]):>7}"
                          for m in MIX_ORDER if m in mix[year])
        print(f"    {year}   {parts}   합계 {cd.human(sum(mix[year].values()))}")

    if consensus:
        print(f"\n  컨센서스가 함의하는 기타 매출 (우리 모델 준비금 수익 "
              f"{cd.human(latest_ri)} 기준)")
        for name, value in consensus.items():
            print(f"    {name}  ->  {cd.human(value)}  "
                  f"(준비금 대비 {value / latest_ri * 100:.1f}%, "
                  f"직전 분기의 {value / rows[-2]['other']:.1f}배)")

    out = args.out or (cd.OUT_DIR / "other_revenue.png")
    plot(rows, mix, consensus, out)
    print(f"\n저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
