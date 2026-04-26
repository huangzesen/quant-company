#!/bin/bash
# 灵台量化 · 报告仪表盘启动脚本
# 用法: ./scripts/start_dashboard.sh [port]

PORT=${1:-8501}
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "📊 灵台量化 — 报告仪表盘"
echo "========================"
echo "项目目录: ${PROJECT_DIR}"
echo "端口:     ${PORT}"
echo ""

cd "${PROJECT_DIR}" || exit 1

streamlit run scripts/dashboard.py \
    --server.port "${PORT}" \
    --server.headless true \
    --browser.gatherUsageStats false \
    --server.enableCORS false
