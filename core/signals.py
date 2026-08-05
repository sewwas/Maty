import json
import urllib.request
import urllib.parse
from typing import Dict, Any, Optional

def send_telegram_alert(bot_token: str, chat_id: str, title: str, message: str) -> bool:
    """
    Dispatches formatted trade alerts, profit updates, and risk warnings to a Telegram channel or group.
    """
    if not bot_token or not chat_id:
        return False

    formatted_text = f"🤖 <b>PROFITY AI ALERT</b>\n\n📌 <b>{title}</b>\n{message}"
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": formatted_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status == 200
    except Exception as e:
        print(f"Telegram dispatch notice: {e}")
        return False

def dispatch_trade_exit_signal(bot_token: str, chat_id: str, symbol: str, cycle_data: Dict[str, Any]) -> bool:
    """
    Dispatches formatted cycle exit summary to Telegram channel.
    """
    pnl = cycle_data.get("pnl", 0.0)
    pnl_symbol = "💰" if pnl >= 0 else "🔻"
    reason = cycle_data.get("exit_reason", "MANUAL")
    duration = cycle_data.get("exit_time", 0) - cycle_data.get("start_time", 0)
    
    title = f"{pnl_symbol} CYCLE CLOSED: {symbol}"
    msg = (
        f"• <b>Exit Reason</b>: <code>{reason}</code>\n"
        f"• <b>Realized PnL</b>: <b>{'+' if pnl>=0 else ''}${pnl:,.2f} USD</b>\n"
        f"• <b>Trades Executed</b>: {cycle_data.get('trades_count', 0)}\n"
        f"• <b>Duration</b>: {int(duration)}s"
    )
    return send_telegram_alert(bot_token, chat_id, title, msg)
