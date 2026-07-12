"""π̂ 准入估计与 (a, θ) 几何扫描（STRATEGY_LOGIC §2 / §10.1）。

用法：
  # 单点估计（当前参数是否过 C8 准入线）
  python backend/tools/calibrate.py --klines var/calibration/BTCUSDT_1h.json \
      --a 1.5 --theta 4.0 --cost 0.14

  # 几何扫描（寻找期望值最优的触发几何）
  python backend/tools/calibrate.py --klines var/calibration/BTCUSDT_1h.json --scan
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.domain.calibration.estimators import estimate, geometry_scan  # noqa: E402


def load_closes(path: str) -> list[float]:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    return [float(row[1]) for row in rows]


def print_report(report: dict) -> None:
    verdict = "PASS 准入" if report["admitted"] else "FAIL 不准入"
    print(f"a={report['a_pct']:.2f}%  θ={report['theta_pct']:.2f}%  c={report['cost_pct']:.2f}%")
    print(f"  excursions={report['excursions']}  回归={report['reversions']}  延伸={report['extensions']}")
    print(f"  π̂={report['pi_hat']:.3f}  CI=[{report['pi_ci_low']:.3f}, {report['pi_ci_high']:.3f}]")
    print(f"  盈亏平衡线 π_req={report['pi_required']:.3f}  单注期望={report['expected_value_pct']:+.3f}%")
    print(f"  C8 判定：{verdict}（要求 CI 下界 > π_req 且样本 ≥ 30）")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--klines", required=True, help="fetch_klines.py 产出的 JSON")
    parser.add_argument("--a", type=float, default=1.5, help="偏斜触发幅度 %")
    parser.add_argument("--theta", type=float, default=4.0, help="趋势确认幅度 %")
    parser.add_argument("--cost", type=float, default=0.14, help="一来一回成本率 %（taker≈0.14，maker≈0.05）")
    parser.add_argument("--scan", action="store_true", help="扫描 (a, θ) 网格")
    args = parser.parse_args()

    closes = load_closes(args.klines)
    print(f"载入 {len(closes)} 根收盘价\n")

    if args.scan:
        a_grid = [1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]
        theta_grid = [2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0]
        rows = geometry_scan(closes, a_grid, theta_grid, args.cost)
        print(f"{'a%':>6} {'θ%':>6} {'π̂':>7} {'CI低':>7} {'π_req':>7} {'E%':>8} {'样本':>5} 准入")
        for row in rows[:20]:
            flag = "✓" if row["admitted"] else "-"
            print(
                f"{row['a_pct']:>6.2f} {row['theta_pct']:>6.2f} {row['pi_hat']:>7.3f}"
                f" {row['pi_ci_low']:>7.3f} {row['pi_required']:>7.3f}"
                f" {row['expected_value_pct']:>+8.3f} {row['excursions']:>5} {flag}"
            )
        positives = [row for row in rows if row["admitted"]]
        print(f"\n{len(positives)}/{len(rows)} 组合过 C8 准入线。")
        if not positives:
            print("警告：没有组合过线——该 symbol 在此周期不适合本策略（诚实的负结果）。")
    else:
        print_report(estimate(closes, args.a, args.theta, args.cost))


if __name__ == "__main__":
    main()
