import json
import time
import logging
from bridge_client import Bot6BridgeClient
from strategy import StrategyEngine

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("bot6.main")

# ── Timeframe map: config key → bridge API value ────────────────────────────
TF_MAP = {
    "1M":  "1m",
    "3M":  "3m",
    "5M":  "5m",
    "15M": "15m",
    "30M": "30m",
    "1H":  "1h",
    "4H":  "4h",
    "1D":  "1d",
}

# Seconds per candle for cooldown calculation
TF_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300,
    "15m": 900, "30m": 1800, "1h": 3600,
    "4h": 14400, "1d": 86400,
}

# After a trade, block same symbol for this many candles (Bug #6 FIX)
COOLDOWN_CANDLES = 3


import os as _os

def load_config():
    # Always resolve config.json relative to THIS script, not the cwd
    _here = _os.path.dirname(_os.path.abspath(__file__))
    with open(_os.path.join(_here, "config.json"), "r") as f:
        return json.load(f)


def run():
    config = load_config()
    client = Bot6BridgeClient(magic_number=config["magic_number"])

    if not client.is_healthy():
        logger.error("❌ Bridge is not running on port 8006. Start start_bridges.bat first!")
        return

    # Bug #7 FIX: enable_symbol is missing from bridge_client — call safely
    for sym in config["symbols"]:
        if hasattr(client, "enable_symbol"):
            client.enable_symbol(sym)
        else:
            logger.debug(f"enable_symbol not available on bridge client, skipping for {sym}")

    # Bug #2 FIX: pass the FULL config dict (StrategyEngine now handles both forms)
    engine = StrategyEngine(config)

    # Bug #5 FIX: validate timeframe is known, warn + fallback if not
    cfg_tf = config.get("timeframe", "1M")
    bridge_tf = TF_MAP.get(cfg_tf)
    if bridge_tf is None:
        logger.warning(
            f"⚠️  Timeframe '{cfg_tf}' not in TF_MAP. Falling back to '1m'. "
            f"Valid values: {list(TF_MAP.keys())}"
        )
        bridge_tf = "1m"
    else:
        logger.info(f"Timeframe mapping: config='{cfg_tf}' → bridge='{bridge_tf}'")

    # Bug #6 FIX: per-symbol cooldown tracking
    cooldown_seconds = TF_SECONDS.get(bridge_tf, 60) * COOLDOWN_CANDLES
    last_trade_time: dict[str, float] = {}

    # Bug #3 FIX: fetch enough bars (500) so vp_lookback=200 is always satisfied
    candle_limit = max(500, config.get("strategy_params", {}).get("volume_profile_lookback", 200) * 3)

    logger.info(
        f"🚀 Bot 6 (FVG Crossfire) Started | "
        f"Symbols={config['symbols']} | TF={cfg_tf} ({bridge_tf}) | "
        f"Candles={candle_limit} | Cooldown={cooldown_seconds}s"
    )

    try:
        while True:
            for symbol in config["symbols"]:

                # ── Bug #6: Skip if still in cooldown ───────────────────────
                elapsed = time.time() - last_trade_time.get(symbol, 0)
                if elapsed < cooldown_seconds:
                    remaining = int(cooldown_seconds - elapsed)
                    logger.debug(f"⏳ {symbol} in cooldown — {remaining}s remaining")
                    continue

                # ── Fetch candles ────────────────────────────────────────────
                df = client.get_candles(symbol, bridge_tf, limit=candle_limit)

                # Bug #5 FIX: log empty data instead of silently continuing
                if df.empty:
                    logger.warning(
                        f"⚠️  Empty candle data for {symbol} on '{bridge_tf}'. "
                        f"Check bridge supports this timeframe."
                    )
                    continue

                logger.debug(f"{symbol}: {len(df)} bars received")

                # ── Run strategy ────────────────────────────────────────────
                result = engine.analyze(df)

                if result["signal"] == 0:
                    continue

                # ── Signal fired — get current tick ─────────────────────────
                tick = client.get_tick(symbol)
                if not tick:
                    logger.warning(f"⚠️  Could not get tick for {symbol}. Skipping trade.")
                    continue

                lot    = config["risk_management"]["lot_size"]
                action = "BUY" if result["signal"] == 1 else "SELL"
                price  = tick["ask"] if result["signal"] == 1 else tick["bid"]

                sl_pips = config["risk_management"]["default_sl_pips"]
                tp_pips = config["risk_management"]["default_tp_pips"]

                # Gold (XAUUSD) uses a different pip size than forex pairs
                if "XAU" in symbol or "GOLD" in symbol.upper():
                    point = 0.01   # Gold: 1 pip = $0.01
                elif "JPY" in symbol:
                    point = 0.001
                else:
                    point = 0.00001

                # Dynamic SL from strategy (Anti-Stop-Hunt) or fallback fixed pips
                if config["risk_management"]["use_dynamic_sl"] and "sl" in result:
                    sl = result["sl"]
                else:
                    sl = (
                        price - (sl_pips * point * 10) if result["signal"] == 1
                        else price + (sl_pips * point * 10)
                    )

                # Validate SL is on the correct side of price
                if result["signal"] == 1 and sl >= price:
                    logger.warning(f"⚠️  BUY SL {sl:.5f} >= price {price:.5f}. Using fixed SL.")
                    sl = price - (sl_pips * point * 10)
                elif result["signal"] == -1 and sl <= price:
                    logger.warning(f"⚠️  SELL SL {sl:.5f} <= price {price:.5f}. Using fixed SL.")
                    sl = price + (sl_pips * point * 10)

                tp1_dist = tp_pips * point * 10
                tp2_dist = tp1_dist * config["risk_management"].get("tp2_multiplier", 2.0)

                tp1 = price + tp1_dist if result["signal"] == 1 else price - tp1_dist
                tp2 = price + tp2_dist if result["signal"] == 1 else price - tp2_dist

                logger.info(
                    f"📊 Signal: {action} {symbol} | Price={price:.5f} | "
                    f"SL={sl:.5f} | TP1={tp1:.5f} | TP2={tp2:.5f} | POC={result.get('poc', 0):.5f}"
                )

                # ── Trade 1: TP1 ─────────────────────────────────────────────
                res1 = client.open_trade(
                    symbol=symbol,
                    action=action,
                    volume=lot,
                    stop_loss=sl,
                    take_profit=tp1,
                    comment="Bot6-TP1"
                )

                # ── Trade 2: TP2 Runner ──────────────────────────────────────
                res2 = client.open_trade(
                    symbol=symbol,
                    action=action,
                    volume=lot,
                    stop_loss=sl,
                    take_profit=tp2,
                    comment="Bot6-TP2"
                )

                # Bug #6 FIX: record trade time to enforce cooldown
                if res1.get("success") or res1.get("ticket") or res2.get("success") or res2.get("ticket"):
                    last_trade_time[symbol] = time.time()
                    logger.info(f"⏱️  Cooldown started for {symbol} — {cooldown_seconds}s")

            time.sleep(5)

    except KeyboardInterrupt:
        logger.info("🛑 Bot 6 stopped by user.")


if __name__ == "__main__":
    run()
