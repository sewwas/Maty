#!/usr/bin/env python3
"""
Profity AI - Unified VPS Web Portal (Port 80)
Serves a command center landing page that links to all 3 trading bots.
"""

import http.server
import socket
import socketserver
import json
import urllib.parse
from http import HTTPStatus

PORT = 80

def is_port_listening(port, host="127.0.0.1", timeout=0.5):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False

PORTAL_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Profity AI — Trading Systems Command Hub</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #090d16;
            --card-bg: rgba(22, 27, 38, 0.85);
            --card-border: rgba(255, 255, 255, 0.08);
            --card-hover-border: rgba(56, 189, 248, 0.4);
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --accent-blue: #38bdf8;
            --accent-green: #10b981;
            --accent-purple: #a855f7;
            --accent-gold: #f59e0b;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            background-color: var(--bg);
            background-image: 
                radial-gradient(at 0% 0%, rgba(56, 189, 248, 0.12) 0px, transparent 50%),
                radial-gradient(at 100% 100%, rgba(168, 85, 247, 0.1) 0px, transparent 50%);
            color: var(--text-main);
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            align-items: center;
            padding: 2.5rem 1.5rem;
        }

        .container {
            max-width: 1080px;
            width: 100%;
        }

        header {
            text-align: center;
            margin-bottom: 3rem;
        }

        .badge-live {
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            background: rgba(16, 185, 129, 0.12);
            border: 1px solid rgba(16, 185, 129, 0.3);
            color: var(--accent-green);
            padding: 0.35rem 0.85rem;
            border-radius: 9999px;
            font-size: 0.8rem;
            font-weight: 600;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            margin-bottom: 1rem;
        }

        .dot-pulse {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background-color: var(--accent-green);
            box-shadow: 0 0 10px var(--accent-green);
            animation: pulse 1.8s infinite;
        }

        @keyframes pulse {
            0%, 100% { transform: scale(1); opacity: 1; }
            50% { transform: scale(1.4); opacity: 0.6; }
        }

        h1 {
            font-size: 2.75rem;
            font-weight: 800;
            letter-spacing: -0.03em;
            background: linear-gradient(135deg, #ffffff 0%, #cbd5e1 50%, #94a3b8 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 0.75rem;
        }

        .subtitle {
            color: var(--text-muted);
            font-size: 1.1rem;
            max-width: 600px;
            margin: 0 auto;
            line-height: 1.6;
        }

        .grid-cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2.5rem;
        }

        .card {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 16px;
            padding: 1.75rem;
            backdrop-filter: blur(12px);
            transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
            position: relative;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }

        .card:hover {
            transform: translateY(-4px);
            border-color: var(--card-hover-border);
            box-shadow: 0 12px 30px -10px rgba(0, 0, 0, 0.5);
        }

        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 1.25rem;
        }

        .card-icon {
            width: 48px;
            height: 48px;
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.5rem;
        }

        .icon-bot1 { background: rgba(56, 189, 248, 0.15); border: 1px solid rgba(56, 189, 248, 0.25); }
        .icon-bot2 { background: rgba(245, 158, 11, 0.15); border: 1px solid rgba(245, 158, 11, 0.25); }
        .icon-bot3 { background: rgba(168, 85, 247, 0.15); border: 1px solid rgba(168, 85, 247, 0.25); }

        .port-tag {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.8rem;
            color: var(--text-muted);
            background: rgba(255, 255, 255, 0.05);
            padding: 0.3rem 0.6rem;
            border-radius: 6px;
            border: 1px solid rgba(255, 255, 255, 0.08);
        }

        .card-title {
            font-size: 1.35rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
        }

        .card-desc {
            color: var(--text-muted);
            font-size: 0.92rem;
            line-height: 1.55;
            margin-bottom: 1.5rem;
        }

        .card-meta {
            display: flex;
            align-items: center;
            gap: 1rem;
            margin-bottom: 1.5rem;
            font-size: 0.85rem;
            color: #64748b;
        }

        .card-meta span {
            display: flex;
            align-items: center;
            gap: 0.35rem;
        }

        .status-dot {
            width: 7px;
            height: 7px;
            border-radius: 50%;
            background-color: var(--accent-green);
        }

        .btn-launch {
            display: block;
            text-align: center;
            text-decoration: none;
            padding: 0.85rem 1.25rem;
            border-radius: 10px;
            font-weight: 600;
            font-size: 0.95rem;
            transition: all 0.2s ease;
            cursor: pointer;
        }

        .btn-blue {
            background: #0284c7;
            color: #ffffff;
        }
        .btn-blue:hover { background: #0369a1; }

        .btn-gold {
            background: #d97706;
            color: #ffffff;
        }
        .btn-gold:hover { background: #b45309; }

        .btn-purple {
            background: #9333ea;
            color: #ffffff;
        }
        .btn-purple:hover { background: #7e22ce; }

        .notice-box {
            background: rgba(30, 41, 59, 0.6);
            border: 1px solid rgba(255, 255, 255, 0.07);
            border-radius: 12px;
            padding: 1.25rem 1.5rem;
            font-size: 0.88rem;
            color: var(--text-muted);
            line-height: 1.6;
            margin-bottom: 2.5rem;
        }

        .notice-box strong {
            color: var(--text-main);
        }

        .notice-box code {
            font-family: 'JetBrains Mono', monospace;
            background: rgba(0, 0, 0, 0.3);
            padding: 0.15rem 0.4rem;
            border-radius: 4px;
            color: var(--accent-blue);
        }

        footer {
            text-align: center;
            color: #475569;
            font-size: 0.85rem;
        }

        @media (max-width: 640px) {
            h1 { font-size: 2.1rem; }
            .grid-cards { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="badge-live">
                <span class="dot-pulse"></span>
                Institutional VPS Core Active
            </div>
            <h1>Profity AI Command Center</h1>
            <p class="subtitle">Unified access portal for live algorithmic trading engines and supervision desks.</p>
        </header>

        <div class="grid-cards">
            <!-- Bot 1: Auto Grid -->
            <div class="card">
                <div>
                    <div class="card-header">
                        <div class="card-icon icon-bot1">⚡</div>
                        <div class="port-tag">PORT 8501</div>
                    </div>
                    <div class="card-title">Bot #1 — Auto Grid</div>
                    <div class="card-desc">Breakout Grid Engine with Smart Runner Mode, Auto-Regime Reading, and Hardened Risk Ceilings.</div>
                    <div class="card-meta">
                        <span><span class="status-dot"></span> Online</span>
                        <span>• Wine Prefix 1</span>
                        <span>• Account #160142171</span>
                    </div>
                </div>
                <a id="link-bot1" href="http://" class="btn-launch btn-blue">Open Auto Grid Desk &rarr;</a>
            </div>

            <!-- Bot 2: Manual Grid Desk -->
            <div class="card">
                <div>
                    <div class="card-header">
                        <div class="card-icon icon-bot2">🕹️</div>
                        <div class="port-tag">PORT 8502</div>
                    </div>
                    <div class="card-title">Bot #2 — Manual Grid Desk</div>
                    <div class="card-desc">Interactive manual control panel for precision trap deployment, live monitoring, and manual cycle executions.</div>
                    <div class="card-meta">
                        <span><span class="status-dot"></span> Online</span>
                        <span>• Wine Prefix 2</span>
                        <span>• Account #257515247</span>
                    </div>
                </div>
                <a id="link-bot2" href="http://" class="btn-launch btn-gold">Open Manual Desk &rarr;</a>
            </div>

            <!-- Bot 3: Trend System -->
            <div class="card">
                <div>
                    <div class="card-header">
                        <div class="card-icon icon-bot3">📈</div>
                        <div class="port-tag">PORT 8503</div>
                    </div>
                    <div class="card-title">Bot #3 — London Asian Trend</div>
                    <div class="card-desc">24/7 autonomous Asian session box breakout & London trend confirmation trading system.</div>
                    <div class="card-meta">
                        <span><span class="status-dot"></span> Online</span>
                        <span>• 24/7 Daemon</span>
                        <span>• Strategy v2.1</span>
                    </div>
                </div>
                <a id="link-bot3" href="http://" class="btn-launch btn-purple">Open Trend Panel &rarr;</a>
            </div>
        </div>

        <div class="notice-box">
            💡 <strong>Browser Connection Tip:</strong> Always make sure to use <code>http://</code> (not <code>https://</code>) when bookmarking or directly opening dashboard ports (e.g. <code>http://169.58.190.245:8501</code>). Using <code>https://</code> without SSL will cause your browser to report <code>ERR_EMPTY_RESPONSE</code>.
        </div>
    </div>

    <footer>
        Profity AI Systems &bull; High Frequency / Low Latency Deployment &bull; 169.58.190.245
    </footer>

    <script>
        // Dynamically assign target ports using current host IP
        const host = window.location.hostname || "169.58.190.245";
        document.getElementById("link-bot1").href = "http://" + host + ":8501";
        document.getElementById("link-bot2").href = "http://" + host + ":8502";
        document.getElementById("link-bot3").href = "http://" + host + ":8503";
    </script>
</body>
</html>
"""

class PortalHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/status":
            status = {
                "bot1": is_port_listening(8501),
                "bot2": is_port_listening(8502),
                "bot3": is_port_listening(8503),
            }
            body = json.dumps(status).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        body = PORTAL_HTML.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # Suppress verbose logging
        pass

def run():
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("0.0.0.0", PORT), PortalHandler) as httpd:
        print(f"Profity AI Portal running on http://0.0.0.0:{PORT}")
        httpd.serve_forever()

if __name__ == "__main__":
    run()
