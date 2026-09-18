#!/usr/bin/env python3
"""유통비용을 상대방별로 쪼개 본다.

Circle의 "Distribution, transaction and other costs" 한 줄에는 서로 성격이 다른
것들이 섞여 있다. Coinbase 배분, Binance 등 신규 파트너 지급, 워런트 비용,
그리고 유통과 무관한 거래 처리 비용까지.

계약 구조 (FY2025 10-K):
  1단계  Coinbase 플랫폼에 올라온 USDC  -> 해당 준비금 수익 배분
                                          (Circle의 issuer retention 차감 후)
  2단계  그 밖에서 발생한 수익          -> 다른 파트너 지급분을 뺀 나머지의 절반

흔히 말하는 "Coinbase가 50% 가져간다"는 2단계만 가리킨다. 1단계가 따로 있어서
합산 실효율은 50%를 넘는다. 반대로 Binance 같은 파트너가 늘면 2단계 분모가
줄어 Coinbase 몫이 깎인다.

상대방별 금액은 XBRL에 태깅돼 있지 않고 10-K 본문 서술에만 나온다. 그래서
아래 DISCLOSED에 출처와 함께 적어둔다. 총액과 준비금 수익은 API에서 받는다.

총액은 crcl:DistributionTransactionAndOtherCosts 기준이라 손익계산서의
"Distribution and transaction costs" 줄에 "Other costs"(연 수백만 달러)가
더해진 값이다.

사용 예:
  python distribution_costs.py
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

import matplotlib.pyplot as plt
from matplotlib.patches import Patch

import circle_data as cd

COINBASE_COLOR = "#eb6834"   # slot 2 orange
OTHERS_COLOR = "#1baf7a"     # slot 3 aqua
RATIO_COLOR = "#4a3aa7"      # slot 7 violet

# Circle FY2025 10-K 본문에서 옮긴 값 (단위 USD)
#   "For the years ended December 31, 2025 and 2024, we incurred $1.4 billion
#    and $924.5 million respectively, of distribution costs in connection with
#    our agreements with Coinbase."
#   "...driven by a $438.4 million increase in distribution costs paid to
#    Coinbase..., along with an increase of $152.1 million and $60.4 million in
#    other distribution costs related to Binance and other strategic
#    distribution partnerships, respectively."
# FY2025 Coinbase는 본문이 $1.4B로 반올림돼 있어 증가분에서 역산했다.
DISCLOSED = {
    2023: dict(coinbase=691.3e6, coinbase_exact=True),
    2024: dict(coinbase=924.5e6, coinbase_exact=True),
    2025: dict(coinbase=924.5e6 + 438.4e6, coinbase_exact=False),
}

# 총액 안에서 성격이 확인된 항목들 (상대방별 분해와는 별개 축)
COMPONENTS = [
    (2024, "Binance 일회성 선급금", 60.3e6,
     "2024년 11월 November Binance Agreement 체결 시 일시 지급"),
    (2025, "December 2024 워런트", 23.6e6,
     "crcl:DistributionAndTransactionCostsForWarrants"),
    (2025, "Binance 증가분 (전년 대비)", 152.1e6, "10-K MD&A"),
    (2025, "기타 파트너 증가분 (전년 대비)", 60.4e6, "10-K MD&A"),
]


def plot(rows, out_path):
    fig, (ax_amt, ax_ratio) = plt.subplots(
        2, 1, figsize=(11, 8.0), dpi=160, sharex=True,
        gridspec_kw={"height_ratios": [1.7, 1]})
    fig.patch.set_facecolor(cd.SURFACE)

    xs = list(range(len(rows)))
    labels = [str(r["year"]) for r in rows]

    # --- 위: 상대방별 금액 ----------------------------------------------
    cd.style_axes(ax_amt)
    cb = [r["coinbase"] for r in rows]
    others = [r["total"] - r["coinbase"] for r in rows]
    ax_amt.bar(xs, cb, width=0.5, color=COINBASE_COLOR, zorder=3)
    # 인접한 두 채움 사이에 2px 상당의 표면색 간격을 둔다
    ax_amt.bar(xs, others, width=0.5, bottom=cb, color=OTHERS_COLOR,
               edgecolor=cd.SURFACE, linewidth=2, zorder=3)

    peak = max(r["total"] for r in rows)
    ax_amt.set_ylim(0, peak * 1.34)
    ax_amt.yaxis.set_major_formatter(cd.money_formatter(peak))
    ax_amt.set_ylabel("유통·거래비용", fontsize=10, color=cd.INK_SECONDARY, labelpad=10)

    handles = [Patch(facecolor=COINBASE_COLOR, label="Coinbase"),
               Patch(facecolor=OTHERS_COLOR, label="Binance·기타 파트너·거래비용")]
    leg = ax_amt.legend(handles=handles, loc="upper left", frameon=False,
                        fontsize=9.5, ncol=2)
    for t in leg.get_texts():
        t.set_color(cd.INK_SECONDARY)

    for x, r in zip(xs, rows):
        others = r["total"] - r["coinbase"]
        # 얇은 띠 안에는 글자가 안 들어가므로 비중은 막대 위에 함께 적는다
        ax_amt.annotate(cd.tex_safe(f"{cd.human(r['total'])}\n"
                                    f"Coinbase {r['coinbase'] / r['total'] * 100:.0f}%"),
                        xy=(x, r["total"]), xytext=(0, 8), textcoords="offset points",
                        fontsize=9.5, color=cd.INK_PRIMARY, ha="center", va="bottom",
                        linespacing=1.5, zorder=5)
        ax_amt.annotate(cd.tex_safe(cd.human(r["coinbase"])), xy=(x, r["coinbase"] / 2),
                        fontsize=9.5, color="#ffffff", fontweight="bold",
                        ha="center", va="center", zorder=5)
        # 기타 금액은 띠 오른쪽 바깥에 잉크색으로 — 띠가 얇고 대비도 낮다
        ax_amt.annotate(cd.tex_safe(cd.human(others)),
                        xy=(x + 0.27, r["coinbase"] + others / 2), xytext=(5, 0),
                        textcoords="offset points", fontsize=9,
                        color=cd.INK_PRIMARY, ha="left", va="center", zorder=5)

    # --- 아래: 준비금 수익 대비 실효율 ----------------------------------
    cd.style_axes(ax_ratio)
    cb_rate = [r["coinbase"] / r["reserve"] * 100 for r in rows]
    all_rate = [r["total"] / r["reserve"] * 100 for r in rows]
    ax_ratio.plot(xs, all_rate, color=RATIO_COLOR, linewidth=2, marker="o",
                  markersize=8, markeredgecolor=cd.SURFACE, markeredgewidth=1.5,
                  label="전체", zorder=4)
    ax_ratio.plot(xs, cb_rate, color=COINBASE_COLOR, linewidth=2, marker="o",
                  markersize=8, markeredgecolor=cd.SURFACE, markeredgewidth=1.5,
                  label="Coinbase", zorder=4)
    ax_ratio.axhline(50, color=cd.INK_MUTED, linewidth=1, linestyle=(0, (4, 3)), zorder=2)
    # 연도 마커와 그 값 라벨을 피해 구간 사이 빈 공간에 둔다
    mid = (xs[0] + xs[1]) / 2 if len(xs) > 1 else xs[0]
    ax_ratio.annotate("계약상 2단계 요율 50%", xy=(mid, 50), xytext=(0, -7),
                      textcoords="offset points", fontsize=8.5,
                      color=cd.INK_SECONDARY, va="top", ha="center")

    for x, v in zip(xs, cb_rate):
        ax_ratio.annotate(f"{v:.1f}%", xy=(x, v), xytext=(0, -16),
                          textcoords="offset points", fontsize=9,
                          color=cd.INK_PRIMARY, ha="center", va="top", zorder=5)
    for x, v in zip(xs, all_rate):
        ax_ratio.annotate(f"{v:.1f}%", xy=(x, v), xytext=(0, 10),
                          textcoords="offset points", fontsize=9,
                          color=cd.INK_PRIMARY, ha="center", va="bottom", zorder=5)

    ax_ratio.set_ylim(40, max(all_rate) * 1.16)
    ax_ratio.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax_ratio.set_ylabel("준비금 수익 대비", fontsize=10, color=cd.INK_SECONDARY, labelpad=10)
    ax_ratio.set_xticks(xs)
    ax_ratio.set_xticklabels(labels, fontsize=10, color=cd.INK_SECONDARY)
    leg2 = ax_ratio.legend(loc="upper left", frameon=False, fontsize=9.5, ncol=2)
    for t in leg2.get_texts():
        t.set_color(cd.INK_SECONDARY)

    fig.suptitle("Circle 유통비용 — 상대방별 구성과 실효율", fontsize=15,
                 color=cd.INK_PRIMARY, fontweight="bold", x=0.10, ha="left", y=0.975)
    cd.credit(fig, datetime.now(timezone.utc),
              "SEC EDGAR (CIK 1876042) · 상대방별 금액은 10-K 본문 서술")
    fig.subplots_adjust(left=0.10, right=0.96, top=0.91, bottom=0.09, hspace=0.16)
    cd.OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=cd.SURFACE)
    plt.close(fig)
    return out_path


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="유통비용 상대방별 구성")
    p.add_argument("--refresh", action="store_true", help="캐시 무시하고 재수집")
    p.add_argument("--out", type=str, help="저장 경로")
    args = p.parse_args(argv)

    # 분기를 합치면 결측인 해가 빠지므로 공시된 연간 값을 직접 쓴다
    total = cd.fetch_annual_distribution_costs(args.refresh)
    reserve = cd.fetch_annual_reserve_income(args.refresh)

    rows = []
    for year, disclosed in sorted(DISCLOSED.items()):
        if year not in total or year not in reserve:
            continue
        rows.append(dict(year=year, total=total[year], reserve=reserve[year],
                         coinbase=disclosed["coinbase"],
                         exact=disclosed["coinbase_exact"]))
    if not rows:
        print("데이터가 없습니다.")
        return 1

    print(f"\n  {'연도':6}{'준비금수익':>12}{'유통·거래비용':>14}{'Coinbase':>11}"
          f"{'기타':>10}{'CB비중':>8}{'CB/준비금':>11}{'전체/준비금':>12}")
    for r in rows:
        others = r["total"] - r["coinbase"]
        mark = "" if r["exact"] else " *"
        print(f"  {r['year']:<6}{cd.human(r['reserve']):>12}{cd.human(r['total']):>14}"
              f"{cd.human(r['coinbase']):>11}{cd.human(others):>10}"
              f"{r['coinbase'] / r['total'] * 100:7.1f}%"
              f"{r['coinbase'] / r['reserve'] * 100:10.1f}%"
              f"{r['total'] / r['reserve'] * 100:11.1f}%{mark}")
    print("\n  * FY2025 Coinbase 금액은 본문이 $1.4B로 반올림돼 있어 증가분에서 역산했다.")

    print("\n  총액 안에서 성격이 확인된 항목")
    for year, name, amount, note in COMPONENTS:
        print(f"    {year}  {name:26} {cd.human(amount):>8}   {note}")

    print("\n  계약 구조 (FY2025 10-K)")
    print("    1단계  Coinbase 플랫폼 내 USDC  -> 해당 준비금 수익 배분")
    print("                                       (Circle의 issuer retention 차감 후)")
    print("    2단계  그 밖에서 발생한 수익    -> 다른 파트너 지급분을 뺀 나머지의 절반")
    print("    => 흔히 말하는 50%는 2단계만 가리킨다. 1단계 때문에 실효율이 50%를 넘는다.")

    out = args.out or (cd.OUT_DIR / "distribution_costs.png")
    plot(rows, out)
    print(f"\n저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
