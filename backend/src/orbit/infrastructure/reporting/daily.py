from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any


class DailyReportBuilder:
    def __init__(self, root: Path):
        self.root = root

    def generate(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        report_date = datetime.now().date().isoformat()
        strategy = snapshot["strategy"]
        report_dir = self.root / "reports" / strategy["id"]
        chart_dir = report_dir / "charts"
        chart_dir.mkdir(parents=True, exist_ok=True)

        charts = self._write_charts(snapshot, chart_dir, report_date)
        markdown = self._markdown(snapshot, report_date, charts)
        report_path = report_dir / f"{report_date}.md"
        report_path.write_text(markdown, encoding="utf-8")

        totals = self._totals(snapshot)
        return {
            "id": f"report_{strategy['id']}_{report_date}",
            "date": report_date,
            "strategy_instance_id": strategy["id"],
            "symbol": "ALL",
            "markdown_path": str(report_path.relative_to(self.root)).replace("\\", "/"),
            "charts": charts,
            "start_equity": totals["start_equity"],
            "end_equity": totals["end_equity"],
            "daily_pnl": totals["daily_pnl"],
            "daily_pnl_pct": totals["daily_pnl_pct"],
            "fee_total": totals["fee_total"],
            "slippage_total": totals["slippage_total"],
            "funding_total": totals["funding_total"],
            "net_pnl": totals["daily_pnl"],
            "max_drawdown": totals["max_drawdown"],
            "profit_transfer_count": totals["profit_transfer_count"],
            "loss_side_reduce_count": totals["loss_side_reduce_count"],
            "position_recovery_count": totals["position_recovery_count"],
            "trade_count": len(snapshot.get("trade_events", [])),
            "generated_at": snapshot["server_time"],
        }

    def _totals(self, snapshot: dict[str, Any]) -> dict[str, float]:
        symbols = snapshot["symbols"]
        metric_history = snapshot.get("metric_history", [])
        total_budget = sum(s["budget_usdt"] for s in symbols)
        end_equity = sum(s["equity"] for s in symbols)
        start_equity = metric_history[0]["total_equity"] if metric_history else total_budget
        equity_values = [point["total_equity"] for point in metric_history] or [end_equity]
        running_peak = equity_values[0]
        max_drawdown = 0.0
        for value in equity_values:
            running_peak = max(running_peak, value)
            max_drawdown = min(max_drawdown, value - running_peak)
        return {
            "start_equity": start_equity,
            "end_equity": end_equity,
            "daily_pnl": end_equity - start_equity,
            "daily_pnl_pct": ((end_equity / start_equity) - 1) * 100 if start_equity else 0.0,
            "fee_total": sum(s["fee_total"] for s in symbols),
            "slippage_total": sum(s["slippage_total"] for s in symbols),
            "funding_total": sum(s["funding_total"] for s in symbols),
            "max_drawdown": max_drawdown,
            "profit_transfer_count": sum(s["profit_transfer_count"] for s in symbols),
            "loss_side_reduce_count": sum(s["loss_side_reduce_count"] for s in symbols),
            "position_recovery_count": sum(s["recovery_count"] for s in symbols),
        }

    def _write_charts(self, snapshot: dict[str, Any], chart_dir: Path, report_date: str) -> list[dict[str, str]]:
        charts: list[dict[str, str]] = []
        metric_history = snapshot.get("metric_history", [])
        symbol_history = snapshot.get("symbol_metric_history", {})

        chart_specs = [
            ("总权益曲线", "total_equity", "equity-total"),
            ("累计手续费曲线", "total_fee", "fee-total"),
            ("Profit Transfer 累计曲线", "profit_transfer_count", "profit-transfer-total"),
        ]
        for title, key, slug in chart_specs:
            path = chart_dir / f"{report_date}-{slug}.svg"
            path.write_text(self._line_svg(title, metric_history, key), encoding="utf-8")
            charts.append({"title": title, "path": self._rel(path)})

        daily_path = chart_dir / f"{report_date}-daily-pnl.svg"
        daily_path.write_text(
            self._bar_svg("每日 PnL", [{"label": report_date, "value": self._totals(snapshot)["daily_pnl"]}]),
            encoding="utf-8",
        )
        charts.append({"title": "每日 PnL 柱状图", "path": self._rel(daily_path)})

        for symbol in snapshot["strategy"]["symbols"]:
            points = symbol_history.get(symbol, [])
            for title, key, slug in [
                (f"{symbol} 权益曲线", "equity", f"{symbol.lower()}-equity"),
                (f"{symbol} 净敞口曲线", "net_exposure", f"{symbol.lower()}-net-exposure"),
            ]:
                path = chart_dir / f"{report_date}-{slug}.svg"
                path.write_text(self._line_svg(title, points, key), encoding="utf-8")
                charts.append({"title": title, "path": self._rel(path)})

            position_path = chart_dir / f"{report_date}-{symbol.lower()}-positions.svg"
            position_path.write_text(
                self._multi_line_svg(f"{symbol} Long / Short 仓位曲线", points, ["long_notional", "short_notional"]),
                encoding="utf-8",
            )
            charts.append({"title": f"{symbol} Long / Short 仓位曲线", "path": self._rel(position_path)})

        return charts

    def _markdown(self, snapshot: dict[str, Any], report_date: str, charts: list[dict[str, str]]) -> str:
        strategy = snapshot["strategy"]
        totals = self._totals(snapshot)
        lines = [
            f"# Dynamic Dual Grid V1 日报 - {report_date}",
            "",
            "## 总览",
            "",
            f"- 策略实例: `{strategy['id']}`",
            f"- 运行模式: `{strategy['mode']}`",
            f"- 当前状态: `{strategy['status']}`",
            f"- 开始权益: `{totals['start_equity']:.4f} USDT`",
            f"- 结束权益: `{totals['end_equity']:.4f} USDT`",
            f"- 当日 PnL: `{totals['daily_pnl']:.4f} USDT`",
            f"- 当日 PnL %: `{totals['daily_pnl_pct']:.4f}%`",
            f"- 手续费: `{totals['fee_total']:.4f} USDT`",
            f"- 滑点成本: `{totals['slippage_total']:.4f} USDT`",
            f"- Funding: `{totals['funding_total']:.4f} USDT`",
            f"- 最大回撤: `{totals['max_drawdown']:.4f} USDT`",
            "",
            "## 单币种状态",
            "",
            "| Symbol | State | Equity | Realized PnL | UPNL | Fee | Gross Exposure |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for symbol in snapshot["symbols"]:
            lines.append(
                "| {symbol} | {state} | {equity:.4f} | {realized:.4f} | {upnl:.4f} | {fee:.4f} | {gross:.4f} |".format(
                    symbol=symbol["symbol"],
                    state=symbol["state"],
                    equity=symbol["equity"],
                    realized=symbol["realized_pnl"],
                    upnl=symbol["unrealized_pnl"],
                    fee=symbol["fee_total"],
                    gross=symbol["gross_exposure"],
                )
            )
        lines.extend([
            "",
            "## 策略动作统计",
            "",
            f"- Profit Transfer 次数: `{totals['profit_transfer_count']}`",
            f"- 亏损腿减仓次数: `{totals['loss_side_reduce_count']}`",
            f"- 仓位恢复次数: `{totals['position_recovery_count']}`",
            f"- 交易事件数: `{len(snapshot.get('trade_events', []))}`",
            "",
            "## 图表",
            "",
        ])
        for chart in charts:
            lines.append(f"- [{chart['title']}](/reports/{chart['path'].split('reports/', 1)[-1]})")

        lines.extend([
            "",
            "## 关键策略事件",
            "",
        ])
        for event in snapshot.get("strategy_events", [])[:20]:
            lines.append(
                f"- `{event['timestamp']}` `{event['symbol']}` `{event['event_type']}`: {event['reason']}"
            )
        lines.extend([
            "",
            "## 风控事件",
            "",
        ])
        risks = snapshot.get("risk_events", [])[:20]
        if risks:
            for event in risks:
                lines.append(f"- `{event['timestamp']}` `{event.get('symbol', '-')}` `{event['risk_type']}`: {event['message']}")
        else:
            lines.append("- 无")
        lines.append("")
        return "\n".join(lines)

    def _line_svg(self, title: str, points: list[dict[str, Any]], key: str) -> str:
        values = [float(point.get(key, 0) or 0) for point in points]
        labels = [str(point.get("tick", idx)) for idx, point in enumerate(points)]
        return self._svg_polyline(title, values, labels, "#1f6feb")

    def _multi_line_svg(self, title: str, points: list[dict[str, Any]], keys: list[str]) -> str:
        series = []
        colors = ["#078f52", "#d92d20", "#1f6feb"]
        for index, key in enumerate(keys):
            series.append({
                "label": key,
                "values": [float(point.get(key, 0) or 0) for point in points],
                "color": colors[index % len(colors)],
            })
        return self._svg_multi(title, series)

    def _bar_svg(self, title: str, bars: list[dict[str, Any]]) -> str:
        width, height, pad = 760, 280, 48
        values = [float(bar["value"]) for bar in bars] or [0.0]
        max_abs = max(abs(value) for value in values) or 1.0
        zero = height / 2
        bar_width = (width - pad * 2) / max(len(bars), 1) * 0.52
        chunks = [self._svg_header(width, height, title)]
        for index, bar in enumerate(bars):
            value = float(bar["value"])
            x = pad + index * ((width - pad * 2) / max(len(bars), 1)) + bar_width * 0.45
            bar_height = abs(value) / max_abs * (height / 2 - pad)
            y = zero - bar_height if value >= 0 else zero
            color = "#078f52" if value >= 0 else "#d92d20"
            chunks.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_width:.2f}" height="{bar_height:.2f}" fill="{color}" rx="4"/>')
            chunks.append(f'<text x="{x + bar_width / 2:.2f}" y="{height - 18}" text-anchor="middle" font-size="12" fill="#667085">{escape(str(bar["label"]))}</text>')
        chunks.append(f'<line x1="{pad}" x2="{width - pad}" y1="{zero}" y2="{zero}" stroke="#dce3ee"/>')
        chunks.append("</svg>")
        return "\n".join(chunks)

    def _svg_polyline(self, title: str, values: list[float], labels: list[str], color: str) -> str:
        return self._svg_multi(title, [{"label": title, "values": values, "color": color}])

    def _svg_multi(self, title: str, series: list[dict[str, Any]]) -> str:
        width, height, pad = 760, 280, 48
        all_values = [value for item in series for value in item["values"]]
        if not all_values:
            all_values = [0.0]
        min_value, max_value = min(all_values), max(all_values)
        span = max(max_value - min_value, 1e-9)
        chunks = [self._svg_header(width, height, title)]
        chunks.append(f'<line x1="{pad}" x2="{width - pad}" y1="{height - pad}" y2="{height - pad}" stroke="#dce3ee"/>')
        chunks.append(f'<line x1="{pad}" x2="{pad}" y1="{pad}" y2="{height - pad}" stroke="#dce3ee"/>')
        for item in series:
            values = item["values"]
            if not values:
                continue
            coords = []
            for index, value in enumerate(values):
                x = pad + index / max(len(values) - 1, 1) * (width - pad * 2)
                y = height - pad - ((value - min_value) / span) * (height - pad * 2)
                coords.append(f"{x:.2f},{y:.2f}")
            chunks.append(f'<polyline points="{" ".join(coords)}" fill="none" stroke="{item["color"]}" stroke-width="2.5"/>')
        chunks.append(f'<text x="{pad}" y="{height - 18}" fill="#667085" font-size="12">min {min_value:.4f} / max {max_value:.4f}</text>')
        chunks.append("</svg>")
        return "\n".join(chunks)

    def _svg_header(self, width: int, height: int, title: str) -> str:
        return "\n".join([
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            '<rect width="100%" height="100%" fill="#ffffff"/>',
            f'<text x="24" y="30" fill="#172033" font-size="18" font-weight="700">{escape(title)}</text>',
        ])

    def _rel(self, path: Path) -> str:
        return str(path.relative_to(self.root)).replace("\\", "/")
