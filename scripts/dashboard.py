"""
灵台量化 · 报告仪表盘
Streamlit dashboard — 挂载 reports/ 目录的 Markdown 报告与 PNG 图表
"""

import streamlit as st
import pandas as pd
from pathlib import Path
import re
from datetime import datetime

st.set_page_config(
    page_title="灵台量化 · 报告仪表盘",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

REPORT_DIR = Path(__file__).resolve().parent.parent / "reports"

# ─── 工具函数 ───────────────────────────────────


def list_markdown_reports():
    """列出 reports/ 下所有 Markdown 文件"""
    return sorted(REPORT_DIR.glob("*.md"))


def list_charts():
    """列出 reports/ 下所有 PNG 图表"""
    return sorted(REPORT_DIR.glob("*.png"))


def render_markdown_file(path):
    """读取并渲染 Markdown 文件"""
    content = path.read_text(encoding="utf-8")
    st.markdown(content)


def parse_report_metrics(md_text: str) -> dict:
    """从 Markdown 报告表格中解析指标"""
    metrics = {}
    # 匹配 Markdown 表格行: | 指标名 | 数值 |
    pattern = r"\|\s*(.+?)\s*\|\s*(.+?)\s*\|"
    for match in re.finditer(pattern, md_text):
        key = match.group(1).strip()
        val = match.group(2).strip()
        if key and val and key not in ("指标", "数值", "------"):
            metrics[key] = val
    return metrics


# ─── 侧边栏导航 ────────────────────────────────

st.sidebar.title("📊 灵台量化")
st.sidebar.caption(f"更新于 {datetime.now().strftime('%Y-%m-%d %H:%M')}")

page = st.sidebar.radio(
    "导航",
    ["🏠 总览", "📝 报告列表", "📈 图表集", "📋 指标看板", "⚡ 风控审查"],
)

# ─── 总览页 ─────────────────────────────────────

if page == "🏠 总览":
    st.title("🏠 报告中心总览")

    md_files = list_markdown_reports()
    chart_files = list_charts()

    col1, col2, col3 = st.columns(3)
    col1.metric("报告总数", len(md_files))
    col2.metric("图表总数", len(chart_files))
    col3.metric("报告目录", str(REPORT_DIR))

    st.divider()

    # 显示报告中心索引
    index_path = REPORT_DIR / "index.md"
    if index_path.exists():
        st.subheader("报告中心")
        render_markdown_file(index_path)
    else:
        st.info("报告中心索引 (index.md) 尚未创建。")

    # 最新报告预览
    md_reports = [f for f in md_files if f.name != "index.md"]
    if md_reports:
        st.subheader("最新报告")
        latest = md_reports[-1]
        with st.expander(f"📄 {latest.name}", expanded=True):
            render_markdown_file(latest)
    else:
        st.info("暂无报告。等待策略回测结果...")

# ─── 报告列表页 ─────────────────────────────────

elif page == "📝 报告列表":
    st.title("📝 绩效报告")

    md_files = [f for f in list_markdown_reports() if f.name != "index.md"]

    if not md_files:
        st.info("暂无绩效报告。待 strategy_researcher 完成回测后生成。")
    else:
        for f in reversed(md_files):
            with st.expander(f"📄 {f.stem}"):
                render_markdown_file(f)

# ─── 图表集页 ───────────────────────────────────

elif page == "📈 图表集":
    st.title("📈 图表集")

    charts = list_charts()

    if not charts:
        st.info("暂无图表。待 data 到位后生成。")
    else:
        cols = st.columns(2)
        for i, chart_path in enumerate(charts):
            with cols[i % 2]:
                st.image(str(chart_path), use_container_width=True)
                st.caption(chart_path.name)

# ─── 指标看板页 ─────────────────────────────────

elif page == "📋 指标看板":
    st.title("📋 核心指标看板")

    md_files = [f for f in list_markdown_reports() if f.name != "index.md"]

    if not md_files:
        st.info("暂无指标数据。待首份报告生成后展示。")
    else:
        # 合并所有报告中的指标
        all_metrics = {}
        for f in reversed(md_files):
            text = f.read_text(encoding="utf-8")
            metrics = parse_report_metrics(text)
            all_metrics.update(metrics)

        if all_metrics:
            # 分类展示
            cols = st.columns(4)
            metric_order = [
                ("总收益率", "total_return"),
                ("年化收益率", "annual_return"),
                ("夏普比率", "sharpe_ratio"),
                ("最大回撤", "max_drawdown"),
                ("胜率", "win_rate"),
                ("盈亏比", "profit_factor"),
                ("总交易次数", "total_trades"),
                ("卡玛比率", "calmar_ratio"),
            ]

            display_data = {}
            for label, key in metric_order:
                for k, v in all_metrics.items():
                    if key in k:
                        display_data[label] = v
                        break

            for i, (label, val) in enumerate(display_data.items()):
                with cols[i % 4]:
                    st.metric(label, val)
        else:
            st.info("报告中有指标，但格式暂未匹配。")


# ─── 风控审查页 ─────────────────────────────────

elif page == "⚡ 风控审查":
    st.title("⚡ 风控审查")

    risk_report = REPORT_DIR / "risk_review_BB_Reversion.md"
    if risk_report.exists():
        with st.expander("📋 BB_Reversion 风控审查报告", expanded=True):
            render_markdown_file(risk_report)
        st.subheader("审查结论")
        st.success("✅ 有条件通过 — 进入模拟执行阶段")
        st.info("**条件：**\n- 首阶段仅限 SPY 模拟执行\n- 半凯利仓位 ≤12.5%\n- 连续 2 次亏损即触发熔断冷却\n- 满 30 笔交易后重新评估")
    else:
        st.info("暂无风控审查报告。")
