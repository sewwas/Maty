"""
test_bot1_logic.py — Comprehensive Unit Verification for Bot #1 Auto Grid (Sunrise Engine)
Tests bridge protocol alignment, dictionary parsing, state machine transitions,
duplicate order guards, and zero-price safeguards without requiring a live broker.
"""

import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
import numpy as np
import datetime
import json

# Ensure Bot1 is on python path
_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
_BOT1_DIR = os.path.join(_ROOT_DIR, "Bot1")
if _BOT1_DIR not in sys.path:
    sys.path.insert(0, _BOT1_DIR)

from bridge_client import Bot1BridgeClient
from sunrise_engine import SunriseEngine


class TestBot1BridgeClient(unittest.TestCase):
    def setUp(self):
        self.client = Bot1BridgeClient(bridge_url="http://127.0.0.1:8001", magic_number=101001)

    @patch("requests.Session.get")
    def test_send_order_protocol(self, mock_get):
        """Verify send_order uses GET /order_send with proper query params."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"success": True, "retcode": 10009, "ticket": 554433}
        mock_get.return_value = mock_resp

        res = self.client.send_order(
            action="BUY",
            symbol="XAUUSD",
            volume=0.02,
            price=2900.50,
            sl=2890.0,
            tp=2920.0
        )
        self.assertTrue(res.get("success"))
        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        self.assertIn("/order_send", args[0])
        params = kwargs.get("params", {})
        self.assertEqual(params.get("type"), "BUY")
        self.assertEqual(params.get("volume"), 0.02)
        self.assertEqual(params.get("price"), 2900.50)
        self.assertEqual(params.get("sl"), 2890.0)
        self.assertEqual(params.get("tp"), 2920.0)
        self.assertEqual(params.get("magic"), 101001)

    @patch("requests.Session.get")
    def test_duplicate_order_guard(self, mock_get):
        """Verify that duplicate order within 15 seconds is suppressed."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"success": True, "retcode": 10009}
        mock_get.return_value = mock_resp

        # 1st dispatch
        r1 = self.client.send_order(action="BUY", symbol="XAUUSD", volume=0.01)
        self.assertTrue(r1.get("success"))

        # Immediate 2nd dispatch (same signature)
        r2 = self.client.send_order(action="BUY", symbol="XAUUSD", volume=0.01)
        self.assertFalse(r2.get("success"))
        self.assertIn("suppressed", r2.get("error", "").lower())

    @patch("requests.Session.get")
    def test_position_close_protocol(self, mock_get):
        """Verify position close calls GET /position_close with ticket."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"success": True}
        mock_get.return_value = mock_resp

        res = self.client.close_position(ticket=998811)
        self.assertTrue(res.get("success"))
        args, kwargs = mock_get.call_args
        self.assertIn("/position_close", args[0])
        self.assertEqual(kwargs.get("params", {}).get("ticket"), 998811)

    @patch("requests.Session.get")
    def test_modify_position_protocol(self, mock_get):
        """Verify position modify calls GET /modify_sl_tp with ticket, sl, tp."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"success": True}
        mock_get.return_value = mock_resp

        res = self.client.modify_position(ticket=998811, sl=2895.0, tp=2930.0)
        self.assertTrue(res.get("success"))
        args, kwargs = mock_get.call_args
        self.assertIn("/modify_sl_tp", args[0])
        params = kwargs.get("params", {})
        self.assertEqual(params.get("ticket"), 998811)
        self.assertEqual(params.get("sl"), 2895.0)
        self.assertEqual(params.get("tp"), 2930.0)

    @patch("requests.Session.get")
    def test_close_all_positions_protocol(self, mock_get):
        """Verify emergency kill switch calls GET /close_all."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"success": True, "closed_count": 2}
        mock_get.return_value = mock_resp

        res = self.client.close_all_positions(symbol="XAUUSD")
        self.assertTrue(res.get("success"))
        args, _ = mock_get.call_args
        self.assertIn("/close_all?symbol=XAUUSD", args[0])

    @patch("requests.Session.get")
    def test_get_positions_dict_parsing(self, mock_get):
        """Verify get_positions correctly extracts positions list from bridge dict and filters by magic."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "positions": [
                {"ticket": 101, "symbol": "XAUUSD", "magic": 101001, "comment": "Sunrise BUY M5"},
                {"ticket": 102, "symbol": "XAUUSD", "magic": 998877, "comment": "Other bot trade"},
                {"ticket": 103, "symbol": "XAUUSD", "magic": 101001, "comment": "Auto Grid"}
            ]
        }
        mock_get.return_value = mock_resp

        pos = self.client.get_positions("XAUUSD")
        self.assertEqual(len(pos), 2)
        self.assertEqual(pos[0]["ticket"], 101)
        self.assertEqual(pos[1]["ticket"], 103)

    @patch("requests.Session.get")
    def test_get_candles_dict_parsing(self, mock_get):
        """Verify get_candles extracts rates list from bridge dict into DataFrame."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        now_ts = int(time.time())
        rates_data = []
        for i in range(20):
            rates_data.append({
                "time": now_ts - (20 - i) * 300,
                "open": 2900.0 + i,
                "high": 2902.0 + i,
                "low": 2899.0 + i,
                "close": 2901.0 + i,
                "tick_volume": 150
            })
        mock_resp.json.return_value = {
            "symbol": "XAUUSD",
            "timeframe": "5m",
            "rates": rates_data
        }
        mock_get.return_value = mock_resp

        df = self.client.get_candles("XAUUSD", "5m", 20)
        self.assertIsInstance(df, pd.DataFrame)
        self.assertEqual(len(df), 20)
        self.assertIn("close", df.columns)
        self.assertEqual(df["close"].iloc[-1], 2920.0)


class TestSunriseEngineLogic(unittest.TestCase):
    def setUp(self):
        # Create engine without background daemon thread for isolated testing
        self.engine = SunriseEngine(start_daemon=False)
        self.engine.phase = "SCANNING"
        self.engine.armed_direction = None
        self.engine.pullback_candle_count = 0
        self.engine.breakout_level = None

    def _generate_test_candles(self, n=50, trend="up"):
        now = datetime.datetime.now(datetime.timezone.utc)
        rows = []
        p = 2900.0
        for i in range(n):
            t = now - datetime.timedelta(minutes=5 * (n - i))
            if trend == "up":
                step = 0.5
            elif trend == "down":
                step = -0.5
            else:
                step = 0.0
            o = p
            c = p + step
            h = max(o, c) + 0.3
            l = min(o, c) - 0.3
            rows.append({
                "timestamp": t,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": 100
            })
            p = c
        return pd.DataFrame(rows)

    def test_indicator_calculation(self):
        """Verify indicator calculations on synthetic candles."""
        df = self._generate_test_candles(60, trend="up")
        ind = self.engine._calculate_indicators(df)
        self.assertIn("closed_ema_fast", ind)
        self.assertIn("closed_ema_slow", ind)
        self.assertIn("closed_ema_filter", ind)
        self.assertIn("atr", ind)
        self.assertGreater(ind["atr"], 0)
        self.assertGreater(ind["closed_ema_fast"], ind["closed_ema_slow"])

    def test_scanning_to_armed_transition(self):
        """Verify transition from SCANNING to ARMED upon bullish crossover."""
        df = self._generate_test_candles(60, trend="up")
        self.engine._cached_candles = df
        self.engine._indicators = self.engine._calculate_indicators(df)
        
        # Simulate crossover condition
        self.engine._indicators["prev_closed_close"] = 2890.0
        self.engine._indicators["prev_closed_fast"] = 2891.0  # prev close <= prev fast
        self.engine._indicators["closed_close"] = 2910.0
        self.engine._indicators["closed_ema_fast"] = 2905.0   # closed > fast
        self.engine._indicators["closed_ema_slow"] = 2900.0   # fast > slow
        self.engine._indicators["closed_ema_filter"] = 2880.0 # closed > filter

        self.engine._last_closed_candle_time = "different_time"
        self.engine._evaluate_state_machine(current_price=2910.0)

        self.assertEqual(self.engine.phase, "ARMED")
        self.assertEqual(self.engine.armed_direction, "LONG")
        self.assertEqual(self.engine.pullback_candle_count, 0)

    def test_pullback_and_window_open_transition(self):
        """Verify ARMED moves to WINDOW_OPEN upon detecting red pullback candle."""
        df = self._generate_test_candles(60, trend="up")
        self.engine._cached_candles = df
        self.engine._indicators = self.engine._calculate_indicators(df)

        self.engine.phase = "ARMED"
        self.engine.armed_direction = "LONG"
        self.engine.signal_candle_time = str(df["timestamp"].iloc[-10])

        # Red pullback candle: close < open, but still above slow EMA
        self.engine._indicators["closed_open"] = 2930.0
        self.engine._indicators["closed_close"] = 2928.0
        self.engine._indicators["closed_ema_slow"] = 2920.0
        self.engine._last_closed_candle_time = "different_time_2"

        self.engine._evaluate_state_machine(current_price=2928.0)

        self.assertEqual(self.engine.phase, "WINDOW_OPEN")
        self.assertIsNotNone(self.engine.breakout_level)
        self.assertGreater(self.engine.breakout_level, 2918.0)

    def test_zero_price_safeguard(self):
        """Verify that price 0.0 or negative never triggers a breakout entry."""
        df = self._generate_test_candles(60, trend="down")
        self.engine._cached_candles = df
        self.engine._indicators = self.engine._calculate_indicators(df)

        self.engine.phase = "WINDOW_OPEN"
        self.engine.armed_direction = "SHORT"
        self.engine.breakout_level = 2900.0

        with patch.object(self.engine, "_execute_entry") as mock_entry:
            # Send invalid zero price
            self.engine._evaluate_state_machine(current_price=0.0)
            mock_entry.assert_not_called()
            self.assertEqual(self.engine.phase, "WINDOW_OPEN")

    def test_window_expiry(self):
        """Verify window expires cleanly back to SCANNING after elapsed periods."""
        df = self._generate_test_candles(60, trend="up")
        self.engine._cached_candles = df
        self.engine._indicators = self.engine._calculate_indicators(df)

        self.engine.phase = "WINDOW_OPEN"
        self.engine.armed_direction = "LONG"
        self.engine.breakout_level = 2950.0
        # Set window open time far in the past (more than 10 candles ago)
        self.engine.window_open_candle_time = str(df["timestamp"].iloc[-15])

        # Current price below breakout level
        self.engine._evaluate_state_machine(current_price=2920.0)

        self.assertEqual(self.engine.phase, "SCANNING")
        self.assertIsNone(self.engine.armed_direction)
        self.assertIsNone(self.engine.breakout_level)


if __name__ == "__main__":
    unittest.main(verbosity=2)
