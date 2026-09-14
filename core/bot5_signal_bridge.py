"""
core/bot5_signal_bridge.py
==========================
Shared AI Signal Bridge -- Bot #5 -> Bot #1

Bot #5 AI Engine writes its regime, signal, and dynamic risk to a JSON file
every cycle. Bot #1 Grid Engine reads this file to align its trap direction,
lot sizing, grid gap, and profit target with Bot 5's AI intelligence.

Design principles:
- Zero cross-process coupling (file-based, not socket or shared memory)
- Atomic write (write to .tmp then rename -- prevents partial-read corruption)
- Staleness guard: Bot 1 ignores signals older than 90 seconds
- Graceful fallback: if bridge unavailable, Bot 1 reverts to its default DUAL mode
"""

import os
import json
import time
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger("Bot5SignalBridge")

# -- Bridge file path ---------------------------------------------------------
_BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))
BRIDGE_FILE = os.path.join(_BRIDGE_DIR, "bot5_signal_bridge.json")

# How old (seconds) a signal can be before Bot 1 ignores it
SIGNAL_STALENESS_LIMIT = 90.0


# -- WRITE (called by Bot 5 ai_engine.py) ------------------------------------

def write_bot5_signal(
    regime: Dict[str, Any],
    signal: Dict[str, Any],
    dynamic_risk: Dict[str, Any]
) -> bool:
    """
    Called by Bot #5 _run_loop() every cycle after computing regime, signal,
    and dynamic risk. Atomically writes the latest AI state to the bridge file.
    """
    payload = {
        "available": True,
        "timestamp": time.time(),
        "regime": regime.get("name", "RANGING"),
        "regime_confidence": float(regime.get("confidence", 0.0)),
        "signal": signal.get("direction", "NEUTRAL"),
        "signal_confidence": float(signal.get("confidence", 0.0)),
        "bull_score": float(signal.get("bull_score", 0.0)),
        "bear_score": float(signal.get("bear_score", 0.0)),
        "factors": signal.get("factors", {}),
        "atr": float(signal.get("atr", 1.5)),
        "dynamic_risk": {
            "risk_pct": float(dynamic_risk.get("risk_pct", 1.0)),
            "atr_sl_multiplier": float(dynamic_risk.get("atr_sl_multiplier", 1.5)),
            "tp_rr": float(dynamic_risk.get("tp_rr", 2.0)),
            "confidence_threshold": float(dynamic_risk.get("confidence_threshold", 0.65)),
            "be_trigger_rr": float(dynamic_risk.get("be_trigger_rr", 1.0)),
            "trailing_atr_multiplier": float(dynamic_risk.get("trailing_atr_multiplier", 1.2)),
            "max_positions": int(dynamic_risk.get("max_positions", 2)),
            "regime_mode": str(dynamic_risk.get("regime_mode", ""))
        }
    }

    try:
        tmp_path = BRIDGE_FILE + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp_path, BRIDGE_FILE)
        return True
    except Exception as e:
        logger.warning(f"[Bot5Bridge] Write failed: {e}")
        return False


# -- READ (called by Bot 1 grid_risk.py) ---------------------------------------

def read_bot5_signal() -> Optional[Dict[str, Any]]:
    """
    Called by Bot #1 grid_risk.py before deploying traps.
    Returns the latest Bot 5 AI signal if fresh (< 90s old), else None.
    Bot 1 should treat None as "Bot 5 offline -- use DUAL fallback defaults".
    """
    try:
        if not os.path.exists(BRIDGE_FILE):
            return None

        with open(BRIDGE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        ts = float(data.get("timestamp", 0.0))
        age = time.time() - ts

        if age > SIGNAL_STALENESS_LIMIT:
            logger.info(f"[Bot5Bridge] Signal is stale ({age:.0f}s old) -- Bot 1 using fallback DUAL mode")
            return None

        if not data.get("available", False):
            return None

        return data

    except Exception as e:
        logger.warning(f"[Bot5Bridge] Read failed: {e}")
        return None


def get_bot5_signal_summary() -> str:
    """
    Returns a human-readable one-line summary of the current bridge state.
    Used by Bot 1 dashboard and hub.py telemetry.
    """
    sig = read_bot5_signal()
    if sig is None:
        return "Bot 5 Bridge: OFFLINE / STALE"

    regime = sig.get("regime", "?")
    direction = sig.get("signal", "NEUTRAL")
    conf = int(sig.get("signal_confidence", 0.0) * 100)
    atr = sig.get("atr", 0.0)
    mode = sig.get("dynamic_risk", {}).get("regime_mode", "")
    age = int(time.time() - sig.get("timestamp", 0.0))

    emoji = {"BUY": "[BUY]", "SELL": "[SELL]", "NEUTRAL": "[NEUTRAL]"}.get(direction, "[?]")
    return f"{emoji} Bot5 -> {regime} | {direction} {conf}% | ATR={atr:.2f} | {mode} | {age}s ago"
