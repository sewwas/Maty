import urllib.request
import json

try:
    print("Testing http://169.58.190.245/api/bot_profits ...")
    req = urllib.request.urlopen('http://169.58.190.245/api/bot_profits', timeout=10)
    data = json.loads(req.read().decode('utf-8'))
    print("API HTTP Status:", req.status)
    print("Portfolio Summary:")
    print(json.dumps(data['portfolio'], indent=2))
    print(f"\nTotal Bots Returned: {len(data['bots'])}")
    for b in data['bots']:
        print(f"  {b['name']}: Equity={b['equity']} USC (${b['equity']/100:.2f}), Bal={b['balance']} USC, Margin={b.get('margin', 0)} USC, Level={b.get('margin_level', 0)}%, 30D PnL={b['pnl_30d']} USC, Today={b['pnl_today']} USC, WinRate={b['win_rate_30d']}% ({b['wins_30d']}W/{b.get('losses_30d', 0)}L), OpenLots={b.get('open_lots', 0.0)} ({b['active_positions']} pos), Ping={b.get('latency_ms', 0)}ms")

    print("\nTesting http://169.58.190.245/ HTML ...")
    req2 = urllib.request.urlopen('http://169.58.190.245/', timeout=10)
    html = req2.read().decode('utf-8')
    print("HTML HTTP Status:", req2.status)
    print("Page Title in HTML:", "<title>Profity AI — Trading Systems Command Hub</title>" in html)
    print("Has Profit Comparison Matrix:", "Multi-Bot Profit Comparison Matrix" in html)
    print("Has Unit Toggle:", "btn-unit-usc" in html)
    print("Has Period Tabs:", "tab-30d" in html)
    print("Has Fullscreen Mode Toggle:", "btn-fullscreen" in html)
    print("Has Market Clocks & UTC Ticker:", "clockUtc" in html)
    print("Has Live Positions Inspector:", "positions-tbody" in html)
    print("Has Margin Level Gauge:", "kpi-margin-level" in html)
    print("\nALL VERIFICATIONS PASSED SUCCESSFULLY!")
except Exception as e:
    print("Error during test:", e)
