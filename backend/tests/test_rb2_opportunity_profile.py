from __future__ import annotations

import unittest

from orbit.application.rb2_opportunity_profile import profile_events


class RB2OpportunityProfileTests(unittest.TestCase):
    def rows(self):
        rows = []
        for index in range(100):
            rows.append({"symbol": f"S{index % 12}", "signal_time_ms": (index + 1) * 86_400_000, "net_return_pct": index - 50, "mfe_r": index / 10, "final_return_r": (index - 50) / 10, "features": {"drop_depth_pct": 10 + index / 100, "relative_quote_volume": 1 + index / 100, "volume_trend_3d": "STRICTLY_INCREASING" if index % 2 else "NOT_STRICTLY_INCREASING", "btc_same_window_return_pct": index / 100, "tier": ("HIGH", "MEDIUM", "LOW")[index % 3], "utc_hour": index % 24, "listing_age": "LE_30_DAYS" if index % 4 == 0 else "GT_30_DAYS", "atr_relative_pct": 2 + index / 100}})
        return rows

    def test_four_profile_groups_are_complete(self):
        result = profile_events(self.rows())
        self.assertEqual(set(result), {"event_count", "r_multiple_distribution", "tail_contribution", "frequency", "identifiability"})
        self.assertEqual(result["identifiability"]["group_counts"], {"TOP_10_PCT": 10, "MIDDLE_80_PCT": 80, "BOTTOM_10_PCT": 10})
        self.assertEqual(len(result["identifiability"]["features"]), 8)
        self.assertEqual(set(result["r_multiple_distribution"]["mfe_touch_rate"]), {"gte_1r", "gte_2r", "gte_3r", "gte_5r", "gte_10r"})

    def test_tail_removal_and_profit_pool_definition(self):
        result = profile_events(self.rows())["tail_contribution"]
        self.assertEqual(result["denominator"], "SUM_OF_POSITIVE_NET_RETURNS")
        self.assertEqual(set(result["contribution_share"]), {"top_1_pct", "top_5_pct", "top_10_pct", "top_20_pct"})
        self.assertEqual(result["sign_after_removing_top_10_pct"], "NEGATIVE")

    def test_output_is_descriptive_not_decisive(self):
        result = profile_events(self.rows())
        text = str(result).lower()
        for forbidden in ("verdict", "passed", "failed", "threshold"):
            self.assertNotIn(forbidden, text)

    def test_report_contract_prohibits_lockbox_and_decision_fields(self):
        import json
        from pathlib import Path
        contract = json.loads((Path(__file__).parents[2] / "config/research/rb2_opportunity_profile.v1.json").read_text())
        self.assertEqual(contract["discipline"]["lockbox_access"], "PROHIBITED")
        self.assertFalse(contract["discipline"]["contains_threshold_or_verdict"])
        self.assertLess(contract["training_end_ms"], contract["lockbox_start_ms"])

    def test_runner_has_no_lockbox_boundary_or_command(self):
        from pathlib import Path
        source = (Path(__file__).parents[1] / "tools/run_rb2_opportunity_profile.py").read_text()
        self.assertNotIn("lockbox_end_ms", source)
        self.assertNotIn("confirm-open-lockbox", source)
        self.assertIn('maximum_time_ms=end_ms', source)


if __name__ == "__main__": unittest.main()
