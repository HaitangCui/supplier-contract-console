# -*- coding: utf-8 -*-
"""AI Supplier Contract Assistant（v2 · Agent 探索版）

自然语言查询 + 分析 + 图表。Agent 只持有只读权限；
编辑/删除等写操作保留在 v1（app.py）人工执行（乐观锁 + 二次确认）。
"""

import os

import plotly.graph_objects as go
import streamlit as st

from agent import DB_PATH, get_api_key, run_agent

st.set_page_config(page_title="AI Supplier Contract Assistant", page_icon="🤖", layout="wide")

MAX_DAILY = 20  # 每个会话每日提问上限（公开部署的成本护栏）

EXAMPLES = [
    "华东地区有哪些供应商？",
    "哪些供应商的联系电话是空的？",
    "各区域的供应商数量分布，画个柱状图",
    "2026 采购年度的合约年度有多少份？和 2025 年对比一下",
    "返利条款明细最多的 10 家供应商是谁？",
]

if "messages" not in st.session_state:
    st.session_state.messages = []
if "llm_calls" not in st.session_state:
    st.session_state.llm_calls = 0


def _build_fig(spec, df):
    kind, x, y = spec["kind"], spec["x"], spec["y"]
    if kind == "pie":
        fig = go.Figure(go.Pie(labels=df[x], values=df[y], hole=0.35))
    elif kind == "line":
        fig = go.Figure(go.Scatter(x=df[x], y=df[y], mode="lines+markers"))
    else:
        fig = go.Figure(go.Bar(x=df[x], y=df[y]))
    fig.update_layout(
        template="plotly_white",
        margin=dict(t=30, b=30, l=30, r=10),
        height=360,
    )
    return fig


st.title("🤖 AI Supplier Contract Assistant")
st.caption("v2 · Agent 探索版 —— 自然语言查询 + 分析 + 图表 ｜ 数据与 v1 一致（演示用虚构数据，只读）")

with st.sidebar:
    st.header("🧭 使用说明")
    st.markdown("**架构**：单 Agent + Tool Calling\n\n提问 → LLM → 只读 SQL / 画图工具 → 结果回传 → LLM 总结")
    st.markdown("**安全边界**：Agent 只有只读查询权限；编辑/删除等写操作保留在 v1 人工执行（乐观锁 + 二次确认）")
    st.markdown(f"**限流**：每个会话每天最多 {MAX_DAILY} 次提问（公开部署的成本护栏）")
    st.divider()
    st.subheader("🔧 运行自检")
    st.markdown(f"- API Key：{'✅ 已配置' if bool(get_api_key()) else '❌ 未配置 → 去 App Settings → Secrets 填 DEEPSEEK_API_KEY'}")
    st.markdown(f"- 数据库：{'✅ 正常' if os.path.exists(DB_PATH) else '❌ 找不到 console.db'}")
    st.divider()
    st.subheader("💡 试试这些问题")
    for i, ex in enumerate(EXAMPLES):
        if st.button(ex, key=f"ex{i}", width="stretch"):
            st.session_state.messages.append({"role": "user", "content": ex})
            st.rerun()

# 渲染历史消息
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m.get("df") is not None:
            st.dataframe(m["df"], width="stretch")
        if m.get("chart"):
            st.plotly_chart(_build_fig(m["chart"], m["df"]), width="stretch")

prompt = st.chat_input("用中文问我，比如「华东地区有哪些供应商？」")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    if st.session_state.llm_calls >= MAX_DAILY:
        st.session_state.messages.append(
            {"role": "assistant", "content": f"⚠️ 本会话今日提问已达上限（{MAX_DAILY} 次），刷新页面或明天再来～"}
        )
    else:
        history = [
            {"role": m["role"], "content": m["content"]}
            for m in st.session_state.messages[:-1]
            if m["role"] in ("user", "assistant")
        ][-8:]
        with st.spinner("Agent 思考中…"):
            try:
                r = run_agent(prompt, history=history, api_key=get_api_key())
            except Exception as e:
                r = {"answer": f"出错了：{e}", "df": None, "chart": None}
        st.session_state.messages.append(
            {"role": "assistant", "content": r["answer"], "df": r.get("df"), "chart": r.get("chart")}
        )
        st.session_state.llm_calls += 1
    st.rerun()
