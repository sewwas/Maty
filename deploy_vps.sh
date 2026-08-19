#!/bin/bash
# ==============================================================================
# One-Click Linux Ubuntu + Wine + MT5 (Dual-Bot Engine) Deployment Script
# Target VPS: 169.58.190.245
# ==============================================================================

set -e

echo "🚀 [1/3] Starting Linux Ubuntu + Wine MT5 Dual-Bot deployment..."

# 1. Cleanup old heavy QEMU Windows container
echo "🧹 [2/3] Cleaning up old Windows container..."
docker stop windows 2>/dev/null || true
docker rm windows 2>/dev/null || true

# 2. Deploy lightweight Ubuntu + Wine Web Desktop container (Supports Dual MT5 Terminals)
echo "📦 [3/3] Pulling and launching lightweight Ubuntu Wine MT5 container..."
docker run -d \
  --name mt5_ubuntu_vps \
  --restart always \
  -p 8006:8080 \
  -p 8501:8501 \
  -p 8502:8502 \
  -e HTTP_PASSWORD= \
  fredblgr/ubuntu-novnc:20.04

echo ""
echo "======================================================================"
echo "🎉 SUCCESS! Your Linux VPS Environment is Live!"
echo "======================================================================"
echo "🌐 Web Desktop UI (Wine MT5 Screen):  👉 http://169.58.190.245:8006"
echo "📊 Bot #1 Control Dashboard:           👉 http://169.58.190.245:8501"
echo "📊 Bot #2 Control Dashboard (Separate):👉 http://169.58.190.245:8502"
echo "======================================================================"
echo "💡 Supports BOTH modes:"
echo "   1) Single MT5 mode (1 Exness Account with 2 Bot Grids on :8501)"
echo "   2) Dual MT5 mode   (2 Separate Exness Accounts & MT5 Terminals on :8501 & :8502)"
echo "======================================================================"
