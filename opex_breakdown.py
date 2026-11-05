#!/usr/bin/env python3
"""영업비용을 항목별로 분해한다 — 증가가 어디서 오는지.

이익 기준 밸류에이션(earnings.py)에서 드러난 것은, 경상 RLDC가 줄어드는 동안
영업비용이 늘어 조정 영업이익이 반토막 났다는 사실이었다. 이 스크립트는 그
영업비용을 손익계산서 줄 단위로 쪼갠다.

구성 항목과 태그
  현금 인건비    us-gaap:LaborAndRelatedExpense - us-gaap:ShareBasedCompensation
  주식보상       us-gaap:ShareBasedCompensation
  일반관리비     us-gaap:GeneralAndAdministrativeExpense
  감가상각       us-gaap:DepreciationAndAmortization
  IT 인프라      crcl:InformationTechnologyInfrastructureCosts  (확장 태그)
  마케팅         us-gaap:MarketingExpense
  디지털자산 손익 us-gaap:CryptoAssetRealizedAndUnrealizedGainLossOperating (부호 반전)

  여섯 항목의 합이 us-gaap:OperatingExpenses 와 일치하는지 매 분기 대조한다.
  어긋나면 분해가 틀린 것이므로 경고를 띄운다.

주의 — 주식보상은 전액이 비용이 아니다
  2026Q3 기준 비용 인식분은 $43.1M이고, 별도로 $10.6M이 내부개발 소프트웨어로
  자본화됐다. 자본화분은 영업비용에 잡히지 않고 나중에 감가상각으로 나온다.
  감가상각이 빠르게 느는 이유의 일부가 여기 있다.

  위     분기 영업비용 구성
  가운데  1년 전 대비 증감 — 어느 항목이 밀어올렸나
  아래    경상 RLDC 가운데 영업비용이 가져가는 몫

데이터 출처: SEC EDGAR · DefiLlama · FRED

사용 예:
  python opex_breakdown.py
  python opex_breakdown.py --from 2025Q3
"""

from __future__ import annotations

import argparse

import matplotlib.pyplot as plt

import circle_data as cd
from revenue_model import build, visible

# dataviz 기본 팔레트 슬롯 1~6. node scripts/validate_palette.js 로 검증했다
# (adjacent CVD ΔE 9.1, normal-vision 19.6, 전 항목 PASS). 대비 WARN이 붙는
# 슬롯이 있어 직접 라벨과 표를 함께 낸다.
COMPONENTS = [
    ("현금 인건비", "#2a78d6"),
    ("주식보상", "#eb6834"),
    ("일반관리비", "#1baf7a"),
    ("감가상각", "#eda100"),
    ("IT 인프라", "#e87ba4"),
    ("마케팅", "#008300"),
]
DIGITAL = "디지털자산 손익"
RLDC_COLOR = "#2a78d6"
SHARE_COLOR = "#e34948"   # slot 8 red — 비중이 올라가는 쪽
DEFAULT_FROM = (2025, 3)


def components(refresh: bool = False) -> tuple[list, dict]:
    """[(분기, {항목: 금액}, 공시 합계)] 와 경상 RLDC."""
    comp = cd.fetch_quarterly("LaborAndRelatedExpense", refresh)
    sbc = cd.fetch_quarterly("ShareBasedCompensation", refresh)
    ga = cd.fetch_quarterly("GeneralAndAdministrativeExpense", refresh)
    da = cd.fetch_quarterly("DepreciationAndAmortization", refresh)
    mkt = cd.fetch_quarterly("MarketingExpense", refresh)
    it = cd.fetch_it_infrastructure(refresh)
    dig = cd.fetch_quarterly("CryptoAssetRealizedAndUnrealizedGainLossOperating", refresh)
    total = cd.fetch_quarterly("OperatingExpenses", refresh)

    derived: set = set()
    results = visible(build(
        cd.fetch_supply(cd.COINS["usdc"], refresh),
        cd.fetch_short_rate("DTB3", refresh),
        cd.fetch_reserve_income(refresh, derived),
        cd.fetch_reported_revenue(refresh, derived),
        cd.fetch_distribution_costs(refresh, derived), derived))
    rldc = {r.quarter: r.recurring_rldc for r in results
            if r.reserve_income is not None}

    rows = []
    for q in sorted(total):
        if not all(q in d for d in (comp, sbc, ga, da, mkt, it)):
            continue
        parts = {
            "현금 인건비": comp[q] - sbc[q],
            "주식보상": sbc[q],
            "일반관리비": ga[q],
            "감가상각": da[q],
            "IT 인프라": it[q],
            "마케팅": mkt[q],
            DIGITAL: -dig.get(q, 0.0),
        }
        rows.append((q, parts, total[q]))
    return rows, rldc


def plot(rows, rldc, out_path):
    cd.use_korean_font()
    fig, (ax_mix, ax_delta, ax_share) = plt.subplots(
        3, 1, figsize=(11.5, 11.6), dpi=160,
        gridspec_kw=dict(height_ratios=[1.1, 0.9, 0.75], hspace=0.55))
    fig.patch.set_facecolor(cd.SURFACE)

    labels = [f"{q[0]}Q{q[1]}" for q, *_ in rows]
    xs = range(len(rows))

    # ── 위: 구성. 스택 사이에 2px 서피스 간격을 둔다
    bottom_peak = max(sum(p[n] for n, _ in COMPONENTS) for _, p, _ in rows)
    bottom = [0.0] * len(rows)
    for name, color in COMPONENTS:
        vals = [parts[name] for _, parts, _ in rows]
        ax_mix.bar(xs, vals, bottom=bottom, width=0.64, color=color, label=name,
                   edgecolor=cd.SURFACE, linewidth=1.6)
        for x, (v, b) in enumerate(zip(vals, bottom)):
            if v / max(bottom_peak, 1.0) > 0.055:
                ax_mix.annotate(cd.human(v), (x, b + v / 2), ha="center",
                                va="center", fontsize=8, fontweight="bold",
                                color="white")
        bottom = [b + v for b, v in zip(bottom, vals)]

    for x, b in zip(xs, bottom):
        ax_mix.annotate(cd.human(b), (x, b), textcoords="offset points",
                        xytext=(0, 7), ha="center", fontsize=9,
                        fontweight="bold", color=cd.INK_PRIMARY)

    ax_mix.set_xticks(list(xs))
    ax_mix.set_xticklabels(labels, fontsize=9)
    ax_mix.set_ylim(0, max(bottom) * 1.16)
    ax_mix.set_ylabel("분기 영업비용", fontsize=10, color=cd.INK_SECONDARY, labelpad=10)
    ax_mix.yaxis.set_major_formatter(cd.money_formatter(max(bottom)))
    ax_mix.set_title(cd.tex_safe(
        "분기 영업비용 구성 — 디지털자산 손익(±$2M)은 부호가 바뀌어 제외했다. "
        "얇은 띠의 금액은 표로 확인할 것"),
        fontsize=12.5, fontweight="bold", loc="left", pad=12)
    cd.style_axes(ax_mix)
    ax_mix.legend(frameon=False, fontsize=9, ncol=6, loc="lower left",
                  bbox_to_anchor=(0, -0.26))

    # ── 가운데: 1년 전 대비 항목별 증감. 워터폴로 쌓으면 $11M 짜리 막대가
    #    $200M 축 위에서 선처럼 보여 읽히지 않으므로 0 기준 막대로 그린다
    base_q, base_parts, _ = rows[0]
    last_q, last_parts, _ = rows[-1]
    names = [n for n, _ in COMPONENTS if n != "주식보상"] + [DIGITAL]
    order = sorted(names, key=lambda n: last_parts[n] - base_parts[n], reverse=True)
    deltas = [last_parts[n] - base_parts[n] for n in order]
    colors = [dict(COMPONENTS).get(n, cd.INK_MUTED) for n in order]
    base_total = sum(base_parts[n] for n in names)
    end_total = sum(last_parts[n] for n in names)

    ax_delta.bar(range(len(order)), deltas, width=0.6, color=colors,
                 edgecolor=cd.SURFACE, linewidth=1.4)
    ax_delta.axhline(0, color=cd.INK_PRIMARY, linewidth=1.0)
    for i, (n, d) in enumerate(zip(order, deltas)):
        pct = (last_parts[n] / base_parts[n] - 1) * 100
        tag = (f"{'+' if d >= 0 else ''}{cd.human(d)}\n{pct:+.0f}%"
               if base_parts[n] > 0 and last_parts[n] > 0
               else f"{'+' if d >= 0 else ''}{cd.human(d)}")
        ax_delta.annotate(tag, (i, d), textcoords="offset points",
                          xytext=(0, 8 if d >= 0 else -24), ha="center",
                          fontsize=9, fontweight="bold", color=cd.INK_PRIMARY)
    ax_delta.set_xticks(range(len(order)))
    ax_delta.set_xticklabels(order, fontsize=9.5)
    top = max(deltas)
    ax_delta.set_ylim(min(0, min(deltas)) - top * 0.22, top * 1.35)
    ax_delta.set_ylabel("증감", fontsize=10, color=cd.INK_SECONDARY, labelpad=10)
    ax_delta.yaxis.set_major_formatter(cd.money_formatter(top))
    ax_delta.set_title(cd.tex_safe(
        f"{base_q[0]}Q{base_q[1]} → {last_q[0]}Q{last_q[1]} 항목별 증감 — "
        f"주식보상 제외 영업비용 {cd.human(base_total)} → {cd.human(end_total)} "
        f"({(end_total / base_total - 1) * 100:+.0f}%)"),
        fontsize=12.5, fontweight="bold", loc="left", pad=12)
    cd.style_axes(ax_delta)

    # ── 아래: 경상 RLDC 가운데 영업비용이 가져가는 몫
    share_q = [(q, sum(p[n] for n in names) / rldc[q] * 100)
               for q, p, _ in rows if q in rldc]
    sx = range(len(share_q))
    ax_share.plot(sx, [v for _, v in share_q], color=SHARE_COLOR, marker="o",
                  markersize=7, linewidth=2.4)
    for i, (q, v) in enumerate(share_q):
        dx, ha = (18, "left") if i == 0 else (0, "center")
        ax_share.annotate(f"{v:.0f}%", (i, v), textcoords="offset points",
                          xytext=(dx, 12), ha=ha, fontsize=9.5,
                          fontweight="bold", color=SHARE_COLOR)
    ax_share.set_xticks(list(sx))
    ax_share.set_xticklabels([f"{q[0]}Q{q[1]}" for q, _ in share_q], fontsize=9)
    ax_share.set_ylim(0, max(v for _, v in share_q) * 1.3)
    ax_share.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax_share.set_ylabel("경상 RLDC 대비", fontsize=10, color=cd.INK_SECONDARY,
                        labelpad=10)
    ax_share.set_title("영업비용이 경상 RLDC에서 가져가는 몫 — 나머지가 영업이익이다",
                       fontsize=12.5, fontweight="bold", loc="left", pad=12)
    cd.style_axes(ax_share)

    cd.credit(fig, cd.fetch_price()[-1][0], "SEC EDGAR · DefiLlama · FRED")
    fig.savefig(out_path, bbox_inches="tight", facecolor=cd.SURFACE)
    print(f"\n저장: {out_path}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Circle 영업비용 항목별 분해")
    p.add_argument("--from", dest="start", default="2025Q3",
                   help="시작 분기 (기본: 2025Q3 — 상장 분기의 주식보상 $435M 제외)")
    p.add_argument("--refresh", action="store_true", help="캐시 무시하고 재수집")
    p.add_argument("--out", type=str, help="저장 경로")
    args = p.parse_args(argv)

    year, quarter = int(args.start[:4]), int(args.start[-1])
    rows_all, rldc = components(args.refresh)

    print("\n  분기 영업비용 분해 (공시 합계와 대조)\n")
    head = f"  {'분기':7}" + "".join(f"{n:>11}" for n, _ in COMPONENTS)
    print(head + f"{DIGITAL:>13}{'합계':>10}{'공시':>10}{'차이':>8}")
    for q, parts, total in rows_all:
        line = f"  {q[0]}Q{q[1]:<4}" + "".join(
            f"{cd.human(parts[n]):>11}" for n, _ in COMPONENTS)
        gap = sum(parts.values()) - total
        flag = "" if abs(gap) < 1e5 else "   <- 분해 불일치"
        print(line + f"{cd.human(parts[DIGITAL]):>13}"
              f"{cd.human(sum(parts.values())):>10}{cd.human(total):>10}"
              f"{cd.human(gap):>8}{flag}")

    rows = [r for r in rows_all if r[0] >= (year, quarter)]
    base_q, base_parts, _ = rows[0]
    last_q, last_parts, _ = rows[-1]
    names = [n for n, _ in COMPONENTS if n != "주식보상"] + [DIGITAL]

    print(f"\n  {base_q[0]}Q{base_q[1]} → {last_q[0]}Q{last_q[1]} 증감 "
          f"(주식보상 제외)\n")
    print(f"  {'항목':13}{'전':>10}{'후':>10}{'증감':>10}{'증가율':>9}{'기여':>9}")
    base_total = sum(base_parts[n] for n in names)
    end_total = sum(last_parts[n] for n in names)
    total_delta = end_total - base_total
    for n in names:
        d = last_parts[n] - base_parts[n]
        # 음수(이익) 항목은 증가율이 거꾸로 읽히므로 비워 둔다
        positive = base_parts[n] > 0 and last_parts[n] > 0
        rate = f"{(last_parts[n] / base_parts[n] - 1) * 100:+.0f}%" if positive else "—"
        share = d / total_delta * 100 if total_delta else 0.0
        print(f"  {n:13}{cd.human(base_parts[n]):>10}{cd.human(last_parts[n]):>10}"
              f"{cd.human(d):>10}{rate:>9}{share:>8.0f}%")
    print(f"  {'합계':13}{cd.human(base_total):>10}{cd.human(end_total):>10}"
          f"{cd.human(total_delta):>10}{(end_total / base_total - 1) * 100:>8.0f}%"
          f"{100:>8.0f}%")

    shares = [(q, sum(p[n] for n in names) / rldc[q] * 100)
              for q, p, _ in rows if q in rldc]
    print(f"\n  경상 RLDC 대비 영업비용 (주식보상 제외)")
    print("    " + "   ".join(f"{q[0]}Q{q[1]} {v:.0f}%" for q, v in shares))
    print(f"\n  * 주식보상 중 비용으로 잡히지 않고 자본화된 금액이 따로 있다 "
          f"(2026Q3 $10.6M).\n    자본화분은 나중에 감가상각으로 나온다 — "
          f"감가상각 증가의 일부가 여기서 온다.")

    out = args.out or (cd.OUT_DIR / "opex_breakdown.png")
    cd.OUT_DIR.mkdir(exist_ok=True)
    plot(rows, rldc, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
