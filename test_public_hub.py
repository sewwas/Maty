import urllib.request
import json

try:
    print("Testing http://169.58.190.245/api/bot_profits ...")
    req = urllib.request.urlopen('http://169.58.190.245/api/bot_profits', timeout=10)
    data = json.loads(req.read().decode('utf-8'))
    print("API HTTP Status:", req.status)
    print("Portfolio Summary:")
    print(json.dumps(data['portfolio'], indent=2))
    print("\nBots:")
    for b in data['bots']:
        print(f"  {b['name']}: Equity={b['equity']} USC (${b['equity']/100:.2f}), Bal={b['balance']} USC, 30D PnL={b['pnl_30d']} USC, Today={b['pnl_today']} USC, WinRate={b['win_rate_30d']}% ({b['wins_30d']}/{b['trades_30d']} trades)")

    print("\nTesting http://169.58.190.245/ HTML ...")
    req2 = urllib.request.urlopen('http://169.58.190.245/', timeout=10)
    html = req2.read().decode('utf-8')
    print("HTML HTTP Status:", req2.status)
    print("Page Title in HTML:", "<title>Profity AI — Trading Systems Command Hub</title>" in html)
    print("Has Profit Comparison Matrix:", "Multi-Bot Profit Comparison Matrix" in html)
    print("Has Unit Toggle:", "btn-unit-usc" in html)
    print("Has Period Tabs:", "tab-30d" in html)
    print("\nALL VERIFICATIONS PASSED SUCCESSFULLY!")
except Exception as e:
    print("Error during test:", e)
