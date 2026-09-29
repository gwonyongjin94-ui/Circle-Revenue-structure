#!/usr/bin/env bash
# 모든 차트와 스냅샷을 다시 만든다. 로컬과 GitHub Actions에서 같은 것을 쓴다.
#
# 한 스크립트가 실패해도 나머지는 돌린다 — 외부 API 하나가 죽었다고
# 전체 갱신을 버릴 이유가 없다. 실패가 있으면 마지막에 0이 아닌 값으로 끝내
# Actions가 빨간불을 띄우게 한다.
set -uo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-./.venv/bin/python}"
command -v "$PY" >/dev/null 2>&1 || PY=python3

failed=()
run() {
  echo "--- $*"
  "$PY" "$@" || failed+=("$*")
}

run circle_supply.py
run circle_supply.py --coins usdc --start 2021-06-01 --out output/usdc_only.png
run rate_overlay.py
run rate_overlay.py --placebo
run reserves.py
run market_share.py
run revenue_model.py
run distribution_costs.py
run price_vs_revenue.py
run other_revenue.py
run valuation.py
run volatility.py
run snapshot.py

mkdir -p assets
for f in circle_supply supply_vs_rate supply_vs_rate_placebo reserves market_share \
         revenue_model distribution_costs price_vs_revenue other_revenue \
         valuation volatility; do
  [ -f "output/$f.png" ] && cp "output/$f.png" "assets/$f.png"
done
[ -f output/usdc_only.png ] && cp output/usdc_only.png assets/usdc_supply.png

if [ ${#failed[@]} -gt 0 ]; then
  printf '\n실패한 스크립트:\n'
  printf '  %s\n' "${failed[@]}"
  exit 1
fi
echo "모두 완료"
