import unittest

from monster.dashboard import _execution_funnel, _lane_analytics
from monster.discord_sender import _extract_strike_from_symbol, _fmt_contract_expiry, _title_icon, _should_skip_discord_alert
from monster.paper_trader import _should_force_close_position


class DiscordFormattingTests(unittest.TestCase):
    def test_extract_strike_from_occ_symbol(self):
        self.assertEqual(_extract_strike_from_symbol("AAPL260501C00200000"), 200.0)

    def test_contract_expiry_formats_short_date(self):
        self.assertEqual(_fmt_contract_expiry("2026-05-01"), "5/1/2026")

    def test_title_icon_matches_lane_rules(self):
        self.assertEqual(_title_icon("LOTTO", "CALL"), "🎯")
        self.assertEqual(_title_icon("SWING", "CALL"), "🟢")
        self.assertEqual(_title_icon("SWING", "PUT"), "🔴")

    def test_estimated_trade_is_blocked(self):
        self.assertTrue(_should_skip_discord_alert({"pricing_source": "estimated"}))
        self.assertFalse(
            _should_skip_discord_alert(
                {
                    "pricing_source": "alpaca-indicative",
                    "option_symbol": "AAPL260501C00200000",
                    "contract_price": 3.25,
                }
            )
        )


class DashboardAnalyticsTests(unittest.TestCase):
    def test_execution_funnel_counts_match_flow(self):
        alerts = [
            {"trade_style": "LOTTO", "symbol": "AAPL", "option_symbol": "AAPL260501C00200000", "contract_price": 3.25, "pricing_source": "alpaca-indicative", "discord_sent": True},
            {"trade_style": "LOTTO", "symbol": "MSFT", "option_symbol": "", "contract_price": None, "pricing_source": "estimated", "discord_sent": False},
        ]
        open_positions = [{"style": "LOTTO", "signal_id": "1"}]
        closed_positions = [{"style": "LOTTO", "signal_id": "2", "realized_pnl": 50.0}]

        funnel = _execution_funnel(alerts, open_positions, closed_positions)
        self.assertEqual(funnel["alerts"], 2)
        self.assertEqual(funnel["matched"], 1)
        self.assertEqual(funnel["discord_sent"], 1)
        self.assertEqual(funnel["paper_entered"], 2)

    def test_lane_analytics_uses_paper_ledger(self):
        alerts = [
            {"trade_style": "LOTTO", "symbol": "AAPL", "option_symbol": "AAPL260501C00200000", "contract_price": 3.25, "pricing_source": "alpaca-indicative"},
            {"trade_style": "SWING", "symbol": "MSFT", "option_symbol": "MSFT260508P00300000", "contract_price": 4.10, "pricing_source": "alpaca-indicative"},
        ]
        open_positions = [{"style": "LOTTO", "symbol": "AAPL"}]
        closed_positions = [
            {"style": "LOTTO", "symbol": "AAPL", "realized_pnl": 100.0},
            {"style": "SWING", "symbol": "MSFT", "realized_pnl": -50.0},
        ]

        lanes = _lane_analytics(alerts, open_positions, closed_positions)
        self.assertEqual(lanes["LOTTO"]["alerts"], 1)
        self.assertEqual(lanes["LOTTO"]["paper_entries"], 2)
        self.assertEqual(lanes["LOTTO"]["pnl"], 100.0)
        self.assertEqual(lanes["SWING"]["pnl"], -50.0)


class PaperTraderPolicyTests(unittest.TestCase):
    def test_only_lotto_is_eligible_for_end_of_day_force_close(self):
        self.assertTrue(_should_force_close_position({"style": "LOTTO"}, True))
        self.assertFalse(_should_force_close_position({"style": "SWING"}, True))


if __name__ == "__main__":
    unittest.main()
