#!/usr/bin/env python3
"""이익 기준 밸류에이션 — 조정 영업이익 배수와 RLDC 배수를 나란히 둔다.

왜 이제 와서 이익 배수를 쓸 수 있는가
  2025년에는 못 썼다. 상장에 따른 주식보상이 FY2025에 $566M까지 부풀어
  (전년 $50M) 보고 영업손익이 -$96M이었고, 2025Q2 한 분기에만 $435M이
  잡혔다. 정상화 가정이 결과를 지배하는 상태였다.
  2026년 들어 분기 주식보상이 $43~54M으로 내려앉으면서 그 조건이 풀렸다.

그래도 남는 두 가지 문제
  1. 보고 영업이익 기준 TTM은 2026Q2에야 흑자로 돌아섰다. 배수 관측치가
     두 개뿐이라 범위라고 부를 수 없다. 표에는 적되 밴드로는 쓰지 않는다.
  2. 주식보상을 더해 되돌리는 조정은 그 비용을 공짜로 치는 것이 아니다.
     주식 수가 늘어나는 형태로 주주가 부담한다. 희석률을 함께 출력한다.

  위     분기 손익 구성 — 경상 RLDC에서 영업비용을 빼면 무엇이 남는가
  가운데  TTM 조정 영업이익과 그때그때의 배수
  아래    주당가치 밴드 — RLDC 기준과 이익 기준

데이터 출처: SEC EDGAR · Yahoo Finance · DefiLlama · FRED

사용 예:
  python earnings.py
  python earnings.py --out output/earnings.png
"""

from __future__ import annotations

import argparse

import matplotlib.pyplot as plt

import circle_data as cd
from revenue_model import ONE_OFF_REVENUE, build, visible
from valuation import DERATED_FROM, band, history, price_on, quarter_end, shares_on

RLDC_COLOR = "#2a78d6"      # slot 1 blue   — Circle 몫
OPEX_COLOR = "#8a8985"      # 중간 회색     — 경상 영업비용
SBC_COLOR = "#eb6834"       # slot 2 orange — 주식보상
PROFIT_COLOR = "#1baf7a"    # slot 3 aqua   — 조정 영업이익
PRICE_COLOR = "#4a3aa7"     # slot 7 violet — 현재 주가


def prior_quarters(q: cd.Quarter, n: int = 4) -> list[cd.Quarter]:
    out = []
    for _ in range(n):
        out.append(q)
        q = (q[0] - 1, 4) if q[1] == 1 else (q[0], q[1] - 1)
    return out


def recurring(series: dict[cd.Quarter, float], q: cd.Quarter) -> float:
    """일회성 매출은 영업이익에 그대로 얹히므로 같이 뺀다."""
    return series[q] - ONE_OFF_REVENUE.get(q, (0.0, ""))[0]


def earnings_history(oper, sbc, prices, shares):
    """(분기, 시가총액, TTM 경상 영업이익, TTM 조정 영업이익).

    공시가 나온 분기만 담는다 — 진행 분기를 넣으면 '분기말 주가'가 오늘
    주가라 배수가 자기 자신을 참조하게 된다 (valuation.history 설명 참조).
    """
    out = []
    for q in sorted(oper):
        window = prior_quarters(q)
        if not all(x in oper for x in window):
            continue
        price = price_on(prices, quarter_end(q))
        count = shares_on(shares, quarter_end(q))
        if not (price and count):
            continue
        ttm = sum(recurring(oper, x) for x in window)
        ttm_adj = sum(recurring(oper, x) + sbc.get(x, 0.0) for x in window)
        out.append((q, price * count, ttm, ttm_adj))
    return out


def dilution(shares: cd.Series) -> tuple[float, float, float]:
    """(시작 주식수, 현재 주식수, 연율 증가율)."""
    (first_day, first), (last_day, last) = shares[0], shares[-1]
    years = (last_day - first_day).days / 365
    rate = ((last / first) ** (1 / years) - 1) * 100 if years > 0 else 0.0
    return first, last, rate


def compute(refresh: bool = False) -> dict:
    """이익 기준 밸류에이션에 필요한 값 한 묶음. build_site 도 이것을 쓴다."""
    derived: set = set()
    oper = cd.fetch_quarterly("OperatingIncomeLoss", refresh, derived)
    sbc = cd.fetch_quarterly("ShareBasedCompensation", refresh)
    opex = cd.fetch_quarterly("OperatingExpenses", refresh)
    prices = cd.fetch_price(refresh=refresh)
    shares = cd.fetch_shares_outstanding(refresh)

    model_derived: set = set()
    results = visible(build(
        cd.fetch_supply(cd.COINS["usdc"], refresh),
        cd.fetch_short_rate("DTB3", refresh),
        cd.fetch_reserve_income(refresh, model_derived),
        cd.fetch_reported_revenue(refresh, model_derived),
        cd.fetch_distribution_costs(refresh, model_derived), model_derived))
    rldc = {r.quarter: r.recurring_rldc for r in results
            if r.reserve_income is not None}

    rows = [(q, oper[q], recurring(oper, q), sbc[q],
             rldc[q], opex[q] - sbc[q], sbc[q], recurring(oper, q) + sbc[q])
            for q in sorted(oper) if q in rldc and q in opex and q in sbc]

    hist = earnings_history(oper, sbc, prices, shares)
    derated = [h for h in hist if h[0] >= DERATED_FROM]
    count, current = shares[-1][1], prices[-1][1]

    adj_band = band([mc / a for _, mc, _, a in derated])
    adj_value = tuple(hist[-1][3] * m / count for m in adj_band)

    rldc_all = history(results, prices, shares, reported_only=True)
    rldc_hist = [h for h in rldc_all if h[0] >= DERATED_FROM]
    rldc_band = band([c / l for _, c, _, l in rldc_hist])
    rldc_value = tuple(rldc_all[-1][3] * m / count for m in rldc_band)

    first, last, dil = dilution(shares)
    return dict(
        rows=rows, hist=hist, derated=derated, current=current, shares=count,
        adj_band=adj_band, adj_value=adj_value, ttm_adj=hist[-1][3],
        rldc_band=rldc_band, rldc_value=rldc_value,
        positive=[h for h in derated if h[2] > 0],
        shares_first=first, shares_last=last, dilution_rate=dil,
        adj_ttm=[(q, mc, a, mc / a) for q, mc, _, a in hist],
    )


def plot(rows, bands, current, adj_ttm, out_path):
    cd.use_korean_font()
    fig, (ax_mix, ax_ttm, ax_band) = plt.subplots(
        3, 1, figsize=(11.5, 11.4), dpi=160,
        gridspec_kw=dict(height_ratios=[1.05, 0.95, 0.8], hspace=0.52))
    fig.patch.set_facecolor(cd.SURFACE)

    # ── 위: 분기 손익 구성
    labels = [f"{q[0]}Q{q[1]}" for q, *_ in rows]
    xs = range(len(rows))
    rldc = [r[4] for r in rows]
    opex_ex = [r[5] for r in rows]
    sbc_q = [r[6] for r in rows]
    adj = [r[7] for r in rows]

    ax_mix.bar(xs, rldc, width=0.62, color=RLDC_COLOR, label="경상 RLDC")
    ax_mix.bar(xs, [-v for v in opex_ex], width=0.62, color=OPEX_COLOR,
               label="영업비용 (주식보상 제외)")
    ax_mix.bar(xs, [-v for v in sbc_q], width=0.62,
               bottom=[-v for v in opex_ex], color=SBC_COLOR, label="주식보상")
    ax_mix.plot(xs, adj, color=PROFIT_COLOR, marker="o", markersize=5,
                linewidth=2.2, label="조정 영업이익", zorder=5)
    ax_mix.axhline(0, color=cd.INK_PRIMARY, linewidth=1.0)
    ax_mix.set_xticks(list(xs))
    ax_mix.set_xticklabels(labels, fontsize=9)
    ax_mix.set_ylabel("분기 손익", fontsize=10, color=cd.INK_SECONDARY, labelpad=10)
    ax_mix.yaxis.set_major_formatter(
        cd.money_formatter(max(max(rldc), max(opex_ex) + max(sbc_q))))
    ax_mix.set_title("분기 손익 구성 — 경상 RLDC에서 영업비용을 뺀 것이 이익이다",
                     fontsize=12.5, fontweight="bold", loc="left", pad=12)
    cd.style_axes(ax_mix)
    ax_mix.legend(frameon=False, fontsize=9, ncol=4, loc="lower left",
                  bbox_to_anchor=(0, -0.30))

    for x, v in zip(xs, adj):
        ax_mix.annotate(cd.human(v), (x, v), textcoords="offset points",
                        xytext=(0, 10), ha="center", fontsize=8.5,
                        fontweight="bold", color=PROFIT_COLOR, zorder=6,
                        bbox=dict(boxstyle="round,pad=0.18", facecolor=cd.SURFACE,
                                  edgecolor="none"))

    # 2025Q2 주식보상 $435M이 세로축을 혼자 끌고 내려간다. 지우지 않고 이름을 붙인다 —
    # 이익 배수를 쓸 수 없던 이유가 바로 이 분기다.
    worst = max(range(len(rows)), key=lambda i: sbc_q[i])
    ax_mix.annotate(f"상장 주식보상 {cd.human(sbc_q[worst])}\n이 분기 때문에 이익 배수를 쓸 수 없었다",
                    (worst + 0.36, -(opex_ex[worst] + sbc_q[worst]) * 0.92),
                    textcoords="offset points", xytext=(10, 0),
                    ha="left", va="center",
                    fontsize=9, fontweight="bold", color=SBC_COLOR)

    # ── 가운데: TTM 조정 영업이익과 배수
    tq = [f"{q[0]}Q{q[1]}" for q, *_ in adj_ttm]
    tv = [v for *_, v, _ in adj_ttm]
    tm = [m for *_, m in adj_ttm]
    ax_ttm.plot(range(len(tq)), tv, color=PROFIT_COLOR, marker="o",
                markersize=6, linewidth=2.4)
    ax_ttm.set_xticks(range(len(tq)))
    ax_ttm.set_xticklabels(tq, fontsize=9)
    ax_ttm.set_ylabel("TTM 조정 영업이익", fontsize=10, color=cd.INK_SECONDARY, labelpad=10)
    ax_ttm.yaxis.set_major_formatter(cd.money_formatter(max(tv)))
    ax_ttm.set_ylim(0, max(tv) * 1.42)
    ax_ttm.set_title("TTM 조정 영업이익과 그때의 시총 배수 — 이익은 줄고 있다",
                     fontsize=12.5, fontweight="bold", loc="left", pad=12)
    cd.style_axes(ax_ttm)
    for i, (v, m) in enumerate(zip(tv, tm)):
        # 첫 점은 y축 눈금과 겹치므로 오른쪽으로 밀어준다
        dx = 20 if i == 0 else 0
        ha = "left" if i == 0 else "center"
        ax_ttm.annotate(f"{cd.human(v)}\n{m:.0f}x", (i, v),
                        textcoords="offset points", xytext=(dx, 13),
                        ha=ha, fontsize=8.5, color=cd.INK_SECONDARY)

    # ── 아래: 주당가치 밴드 비교
    names = [b[0] for b in bands]
    ys = range(len(bands))
    for y, (_, lo, mid, hi, color) in zip(ys, bands):
        ax_band.plot([lo, hi], [y, y], color=color, linewidth=13,
                     solid_capstyle="butt", alpha=0.30)
        ax_band.plot([mid, mid], [y - 0.21, y + 0.21], color=color, linewidth=2.6)
        ax_band.annotate(f"${lo:,.0f}", (lo, y), textcoords="offset points",
                         xytext=(-8, 0), ha="right", va="center", fontsize=9.5,
                         color=cd.INK_SECONDARY)
        ax_band.annotate(f"${hi:,.0f}", (hi, y), textcoords="offset points",
                         xytext=(8, 0), ha="left", va="center", fontsize=9.5,
                         color=cd.INK_SECONDARY)
        ax_band.annotate(f"중앙 ${mid:,.0f}", (mid, y), textcoords="offset points",
                         xytext=(0, 15), ha="center", fontsize=9,
                         fontweight="bold", color=color)
    ax_band.axvline(current, color=PRICE_COLOR, linewidth=2.2, zorder=6)
    ax_band.annotate(f"현재 ${current:,.2f}", (current, len(bands) - 0.46),
                     textcoords="offset points", xytext=(7, 0), ha="left",
                     fontsize=10, fontweight="bold", color=PRICE_COLOR)
    ax_band.set_yticks(list(ys))
    ax_band.set_yticklabels(names, fontsize=10)
    ax_band.set_ylim(-0.7, len(bands) - 0.3)
    lows = [b[1] for b in bands] + [current]
    highs = [b[3] for b in bands] + [current]
    pad = (max(highs) - min(lows)) * 0.16
    ax_band.set_xlim(min(lows) - pad, max(highs) + pad)
    ax_band.set_xlabel("주당가치", fontsize=10, color=cd.INK_SECONDARY, labelpad=10)
    ax_band.set_title("기준에 따라 밴드가 다르다 — 이익 기준이 더 낮고 더 넓다",
                      fontsize=12.5, fontweight="bold", loc="left", pad=20)
    cd.style_axes(ax_band)
    ax_band.grid(axis="y", visible=False)

    cd.credit(fig, cd.fetch_price()[-1][0],
              "SEC EDGAR · Yahoo Finance · DefiLlama · FRED")
    fig.savefig(out_path, bbox_inches="tight", facecolor=cd.SURFACE)
    print(f"\n저장: {out_path}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Circle 이익 기준 밸류에이션")
    p.add_argument("--refresh", action="store_true", help="캐시 무시하고 재수집")
    p.add_argument("--out", type=str, help="저장 경로")
    args = p.parse_args(argv)

    c = compute(args.refresh)

    print("\n  분기 손익 — 일회성 매출 제외 기준\n")
    print(f"  {'분기':7}{'경상 RLDC':>12}{'영업비용':>11}{'주식보상':>10}"
          f"{'경상 영업이익':>14}{'조정 영업이익':>14}")
    for q, _, rec, _, rl, ox, sb, adjv in c["rows"]:
        print(f"  {q[0]}Q{q[1]:<4}{cd.human(rl):>12}{cd.human(ox):>11}"
              f"{cd.human(sb):>10}{cd.human(rec):>14}{cd.human(adjv):>14}")

    print("\n  TTM 배수 (공시 분기, 분기말 주가 기준)\n")
    print(f"  {'분기':7}{'시가총액':>11}{'TTM 경상 영업이익':>18}{'배수':>10}"
          f"{'TTM 조정':>12}{'배수':>9}")
    for q, mc, ttm, ttm_adj in c["hist"]:
        m = f"{mc / ttm:.0f}x" if ttm > 0 else "— (적자)"
        print(f"  {q[0]}Q{q[1]:<4}{cd.human(mc):>11}{cd.human(ttm):>18}{m:>10}"
              f"{cd.human(ttm_adj):>12}{mc / ttm_adj:>8.0f}x")

    rv, av, rb, ab = (c["rldc_value"], c["adj_value"],
                      c["rldc_band"], c["adj_band"])
    print(f"\n  주당가치 밴드 ({DERATED_FROM[0]}Q{DERATED_FROM[1]} 이후 배수 범위 적용)\n")
    print(f"    RLDC 기준           ${rv[0]:,.0f} ~ ${rv[2]:,.0f} "
          f"(중앙 ${rv[1]:,.0f})   배수 {rb[0]:.1f}~{rb[2]:.1f}x")
    print(f"    조정 영업이익 기준    ${av[0]:,.0f} ~ ${av[2]:,.0f} "
          f"(중앙 ${av[1]:,.0f})   배수 {ab[0]:.0f}~{ab[2]:.0f}x")
    print(f"    현재 주가           ${c['current']:,.2f}")

    print(f"\n  * 보고 영업이익 기준 밴드는 내지 않았다. {DERATED_FROM[0]}Q{DERATED_FROM[1]} 이후 "
          f"{len(c['derated'])}개 분기 중\n    TTM이 흑자인 분기가 "
          f"{len(c['positive'])}개뿐이라 범위라고 부를 수 없다.")
    print(f"\n  * 조정 영업이익은 주식보상을 비용에서 뺀 값이다. 그 비용은 사라지지 않고\n"
          f"    주식 수로 옮겨간다 — {c['shares_first'] / 1e6:.1f}M주에서 "
          f"{c['shares_last'] / 1e6:.1f}M주로 연 {c['dilution_rate']:.1f}%씩 늘고 있다.\n"
          f"    이익 기준 배수를 볼 때는 주당 이익이 매년 그만큼 희석된다는 점을 같이 봐야 한다.")

    out = args.out or (cd.OUT_DIR / "earnings.png")
    cd.OUT_DIR.mkdir(exist_ok=True)
    bands = [("RLDC 기준", *c["rldc_value"], RLDC_COLOR),
             ("조정 영업이익 기준", *c["adj_value"], PROFIT_COLOR)]
    plot(c["rows"], bands, c["current"], c["adj_ttm"], out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
