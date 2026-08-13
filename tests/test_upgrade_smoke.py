import unittest
from types import SimpleNamespace

from monster.dashboard import _execution_funnel, _lane_analytics, _paper_section
from monster.discord_sender import _extract_strike_from_symbol, _fmt_contract_expiry, _title_icon, _should_skip_discord_alert, _fire_suffix
from monster.options_flow import _classify_time_and_sale_side, _select_sold_alerts_for_posting
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

    def test_fire_suffix_only_shows_for_high_conviction(self):
        self.assertEqual(_fire_suffix({"fire_confidence": 85}, {"confidence": 90}), " 🔥")
        self.assertEqual(_fire_suffix({"fire_confidence": 85}, {"confidence": 84.99}), "")


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

    def test_paper_section_accepts_stringified_numbers(self):
        html = _paper_section(
            {
                "stats": {
                    "total_pnl": "125.50",
                    "lotto_pnl": "125.50",
                    "swing_pnl": "-10",
                    "wins": "2",
                    "losses": "1",
                    "win_rate": "66.7",
                    "lotto_trades": "2",
                    "swing_trades": "1",
                },
                "open_positions": [
                    {
                        "style": "LOTTO",
                        "symbol": "AAPL",
                        "side": "CALL",
                        "option_symbol": "AAPL260501C00200000",
                        "entry_contract_price": "3.25",
                        "current_contract_price": "3.75",
                        "unrealized_pnl": "50",
                        "live_pnl_pct": "15.38",
                        "contracts": "1",
                    }
                ],
                "recent_closed": [
                    {
                        "style": "SWING",
                        "symbol": "MSFT",
                        "side": "PUT",
                        "entry_contract_price": "4.00",
                        "exit_contract_price": "3.50",
                        "realized_pnl": "-50",
                        "contracts_closed": "1",
                    }
                ],
            }
        )

        self.assertIn("AAPL", html)
        self.assertIn("+$125.50", html)
        self.assertIn("$3.25", html)


class PaperTraderPolicyTests(unittest.TestCase):
    def test_only_lotto_is_eligible_for_end_of_day_force_close(self):
        self.assertTrue(_should_force_close_position({"style": "LOTTO"}, True))
        self.assertFalse(_should_force_close_position({"style": "SWING"}, True))


class SoldFlowTests(unittest.TestCase):
    def test_aggressor_side_prefers_explicit_sell_signal(self):
        event = SimpleNamespace(
            aggressor_side="SELL",
            aggressorSide="",
            price=2.5,
            bid_price=2.45,
            bidPrice=2.45,
            ask_price=2.55,
            askPrice=2.55,
        )
        self.assertEqual(_classify_time_and_sale_side(event), "sell")

    def test_aggressor_side_falls_back_to_bid_ask_context(self):
        event = SimpleNamespace(
            aggressor_side="",
            aggressorSide="",
            price=1.0,
            bid_price=1.0,
            bidPrice=1.0,
            ask_price=1.1,
            askPrice=1.1,
        )
        self.assertEqual(_classify_time_and_sale_side(event), "sell")

    def test_sold_alerts_use_independent_namespace_state(self):
        alerts = [
            {
                "streamer_symbol": ".AAPL260501C00200000",
                "contract_symbol": ".AAPL260501C00200000",
                "symbol": "AAPL",
                "strike": 200.0,
                "opt_type": "C",
                "expiry_str": "05/01/2026",
                "dte": 2,
                "volume": 5000,
                "open_interest": 1200,
                "spot": 3.5,
                "premium": 1200000.0,
                "seller_premium": 450000.0,
                "buyer_premium": 100000.0,
                "seller_share": 0.75,
                "seller_volume": 1400,
                "buyer_volume": 300,
                "seller_trades": 7,
                "buyer_trades": 2,
            }
        ]
        state = {
            "recent_contracts": {".AAPL260501C00200000": {"posted_at": "2099-01-01T00:00:00Z"}},
            "recent_symbols": {"AAPL": {"posted_at": "2099-01-01T00:00:00Z"}},
            "last_posted": [],
            "daily_alert_day": "2099-01-01",
            "daily_alert_count": 1,
        }

        selected, meta = _select_sold_alerts_for_posting(alerts, state)
        self.assertEqual(len(selected), 1)
        self.assertEqual(meta["ranked_by"], "seller_premium_then_share")


if __name__ == "__main__":
    unittest.main()
