"""
setup_accounts.py — One-time MT5 Account Setup CLI
====================================================
Run this ONCE to save your MT5 credentials for both bots.
Credentials are stored in bridge_config_8001.json (Bot #1)
and bridge_config_8002.json (Bot #2).

The bridge processes read these files automatically on startup
so they connect to MT5 without needing the in-app login form.

Usage:
    python setup_accounts.py
"""

import json
import os
import sys

CONFIG_FILE_TMPL = "bridge_config_{port}.json"

BANNER = """
╔══════════════════════════════════════════════════════════╗
║           Profity AI — MT5 Account Setup                 ║
║                                                          ║
║  This saves your login credentials for both bot          ║
║  instances so they connect to MT5 automatically.         ║
║                                                          ║
║  ⚠️  Each bot MUST use a DIFFERENT MT5 account number!   ║
╚══════════════════════════════════════════════════════════╝
"""


def prompt(label: str, default: str = "", secret: bool = False) -> str:
    if default:
        display_default = "****" if secret else default
        prompt_str = f"  {label} [{display_default}]: "
    else:
        prompt_str = f"  {label}: "
    try:
        if secret:
            import getpass
            val = getpass.getpass(prompt_str)
        else:
            val = input(prompt_str).strip()
    except (KeyboardInterrupt, EOFError):
        print("\n\nSetup cancelled.")
        sys.exit(0)
    return val if val else default


def save_config(port: int, login: int, password: str, server: str):
    cfg_path = CONFIG_FILE_TMPL.format(port=port)
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"login": login, "password": password, "server": server}, f, indent=2)
    print(f"  ✅ Saved → {cfg_path}")


def load_existing(port: int) -> dict:
    cfg_path = CONFIG_FILE_TMPL.format(port=port)
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def setup_account(bot_num: int, port: int):
    existing = load_existing(port)
    print(f"\n── Bot #{bot_num} (Bridge Port {port}) ──────────────────────────────")
    if existing:
        print(f"  Current account: #{existing.get('login', '?')} on {existing.get('server', '?')}")
        overwrite = prompt("  Overwrite existing credentials? (y/N)", default="N")
        if overwrite.lower() != "y":
            print("  ↳ Keeping existing credentials.")
            return

    login_str = prompt("  MT5 Account Login Number")
    if not login_str.isdigit():
        print("  ⛔ Invalid login number. Skipping Bot #{bot_num}.")
        return

    password = prompt("  MT5 Password", secret=True)
    if not password:
        print("  ⛔ Password cannot be empty. Skipping Bot #{bot_num}.")
        return

    default_srv = "Exness-MT5Real36" if bot_num == 1 else "Exness-MT5Real36"
    server = prompt("  Server Name", default=default_srv)

    save_config(port, int(login_str), password, server)
    print(f"  Bot #{bot_num} → Account #{login_str} @ {server}")


def check_conflict():
    cfg1 = load_existing(8001)
    cfg2 = load_existing(8002)
    if cfg1 and cfg2:
        if str(cfg1.get("login")) == str(cfg2.get("login")):
            print("\n⛔ ERROR: Both bots are configured to use the SAME MT5 account!")
            print("   Each bot must have a unique account number.")
            print("   Re-run this script and enter a different account for Bot #2.\n")
            return False
    return True


if __name__ == "__main__":
    print(BANNER)
    print("You will be prompted to enter credentials for each bot instance.\n")

    setup_account(1, 8001)
    setup_account(2, 8002)

    if not check_conflict():
        sys.exit(1)

    print("\n══════════════════════════════════════════════════════════")
    print("✅  Setup complete! Now start the bridges:")
    print()
    if sys.platform == "win32":
        print("    start_bridges.bat")
    else:
        print("    bash start_bridges.sh")
    print()
    print("Then start the Streamlit app:")
    print("    streamlit run app.py --server.port 8501")
    print("══════════════════════════════════════════════════════════\n")
