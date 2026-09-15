# -*- coding: utf-8 -*-
"""v3 · 报告生成模块：模板月报 + 问答导出（单文件 HTML，浏览器打开可打印 PDF）

两条路径：
- monthly_report_html()：固定模板「供应商月度概况报告」——SQL 取真实数据 + LLM 撰写分析文字
- qa_report_html()：把任意一轮问答（结论 + 表格 + 图表）导出为报告

原则：报告里的所有数字都来自数据库查询结果；LLM 只负责分析文字，
且 prompt 中强制「只能使用提供的数字，禁止编造」。
"""

import json
from datetime import datetime
from html import escape

import markdown as md
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from openai import OpenAI

from agent import MODEL, get_api_key, run_sql

# 国内可访问的 Plotly CDN（jsdelivr），单文件报告需联网渲染图表
PLOTLY_CDN = '<script src="https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js"></script>'

REPORT_CSS = """
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Microsoft YaHei", "PingFang SC", sans-serif;
         background: #F5F7FA; color: #1F2937; line-height: 1.6; }
  .page { max-width: 960px; margin: 24px auto; padding: 32px 40px; background: #FFFFFF;
          border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,.06); }
  header h1 { font-size: 22px; color: #111827; }
  header .meta { margin-top: 6px; font-size: 13px; color: #6B7280; }
  h2 { font-size: 16px; margin: 28px 0 12px; padding-left: 8px; border-left: 4px solid #2563EB; }
  .kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-top: 16px; }
  .kpi { background: #F8FAFC; border: 1px solid #E5E7EB; border-radius: 8px; padding: 14px 16px; }
  .kpi .name { font-size: 13px; color: #6B7280; }
  .kpi .value { font-size: 26px; font-weight: 700; color: #111827; margin-top: 2px; }
  .kpi .sub { font-size: 12px; color: #9CA3AF; }
  .charts { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .chart-card { border: 1px solid #E5E7EB; border-radius: 8px; padding: 12px; }
  .chart-card h3 { font-size: 14px; font-weight: 600; margin-bottom: 4px; }
  table.data-table { width: 100%; border-collapse: collapse; font-size: 13px; margin-bottom: 8px; }
  table.data-table th { background: #EEF2F7; text-align: left; padding: 8px 10px; border: 1px solid #E5E7EB; }
  table.data-table td { padding: 7px 10px; border: 1px solid #E5E7EB; }
  table.data-table tr:nth-child(even) { background: #FAFBFC; }
  .narrative { background: #EFF6FF; border-radius: 8px; padding: 16px 20px; font-size: 14px; }
  footer { margin-top: 28px; padding-top: 12px; border-top: 1px solid #E5E7EB;
           font-size: 12px; color: #9CA3AF; text-align: center; }
</style>
"""


def _fig_bar(df, x, y, color="#2563EB"):
    fig = go.Figure(go.Bar(x=df[x], y=df[y], marker_color=color))
    return _style(fig)


def _fig_pie(df, labels, values):
    fig = go.Figure(go.Pie(labels=df[labels], values=df[values], hole=0.35))
    return _style(fig)


def _style(fig):
    fig.update_layout(template="plotly_white", margin=dict(t=30, b=30, l=30, r=10), height=300)
    return fig


def _fig_html(fig):
    """图表转 HTML 片段（JS 由页面顶部 CDN 统一引入）"""
    return pio.to_html(fig, include_plotlyjs=False, full_html=False)


def _md(text):
    return md.markdown(text or "", extensions=["tables"])


def _page(title, meta, body, footer):
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{title}</title>
{PLOTLY_CDN}
{REPORT_CSS}
</head>
<body>
<div class="page">
<header>
  <h1>{title}</h1>
  <div class="meta">{meta}</div>
</header>
{body}
<footer>{footer}</footer>
</div>
</body>
</html>"""


def _jsonable(x):
    """把 pandas/numpy 标量递归转成原生 Python 类型（json.dumps 需要）"""
    if isinstance(x, dict):
        return {k: _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if hasattr(x, "item"):  # numpy 标量（int64/float64…）
        return x.item()
    return x


def _narrative(api_key, stats):
    """让 LLM 基于查询结果写「月度概览」分析文字（强制只用提供的数字）"""
    prompt = f"""你是供应链采购分析员。以下是供应商合约数据库的统计结果（JSON）：

{json.dumps(_jsonable(stats), ensure_ascii=False)}

请写一段 150-200 字的「月度概览」：先给总体结论，再点出 2-3 个值得关注的点（区域/品类/年度对比/数据质量），最后一句给出建议。
硬性要求：
1. 所有数字必须来自上面 JSON，禁止编造或估算
2. 简体中文，直接输出正文，不用 Markdown 标题和列表符号"""
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com", timeout=60, max_retries=0)
    resp = client.chat.completions.create(
        model=MODEL, messages=[{"role": "user", "content": prompt}], temperature=0.3
    )
    return resp.choices[0].message.content or ""


def monthly_report_html(api_key=None):
    """生成「供应商月度概况报告」。数字全部来自实时 SQL 查询，AI 只写分析文字。"""
    api_key = api_key or get_api_key()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    def one(sql):
        return run_sql(sql).iloc[0, 0]

    # ---- KPI ----
    n_suppliers = one("SELECT COUNT(*) FROM suppliers")
    status_df = run_sql("SELECT status, COUNT(*) AS cnt FROM suppliers GROUP BY status")
    n_contracts = one("SELECT COUNT(*) FROM contracts")
    active_contracts = one("SELECT COUNT(*) FROM contracts WHERE status = '生效中'")
    n_years = one("SELECT COUNT(*) FROM contract_years")
    n_pr = one("SELECT COUNT(*) FROM split_details_pr")
    n_xol = one("SELECT COUNT(*) FROM split_details_xol")
    n_empty_phone = one("SELECT COUNT(*) FROM suppliers WHERE contact_phone IS NULL OR contact_phone = ''")
    avg_discount = one("SELECT ROUND(AVG(base_discount_rate), 4) FROM split_details_pr")

    # ---- 图表数据 ----
    region_df = run_sql("SELECT region, COUNT(*) AS cnt FROM suppliers GROUP BY region ORDER BY cnt DESC")
    category_df = run_sql("SELECT category, COUNT(*) AS cnt FROM suppliers GROUP BY category ORDER BY cnt DESC LIMIT 10")
    year_df = run_sql("SELECT procurement_year, COUNT(*) AS cnt FROM contract_years GROUP BY procurement_year ORDER BY procurement_year")

    # ---- 表格数据 ----
    empty_df = run_sql(
        "SELECT supplier_id AS sid, supplier_name AS sname, region, category "
        "FROM suppliers WHERE contact_phone IS NULL OR contact_phone = '' ORDER BY supplier_id LIMIT 10"
    )
    empty_df.columns = ["编号", "供应商名称", "区域", "品类"]
    rebate_df = run_sql(
        "SELECT s.supplier_name AS sname, s.region, COUNT(x.xol_detail_id) AS cnt, "
        "ROUND(AVG(x.rebate_rate) * 100, 2) AS pct "
        "FROM suppliers s JOIN contracts c ON c.supplier_id = s.supplier_id "
        "JOIN contract_years cy ON cy.contract_id = c.contract_id "
        "JOIN split_details_xol x ON x.contract_year_id = cy.contract_year_id "
        "GROUP BY s.supplier_id ORDER BY cnt DESC LIMIT 10"
    )
    rebate_df.columns = ["供应商名称", "区域", "返利条款数", "平均返利比例(%)"]

    # ---- AI 分析文字（数字只来自上面查询）----
    status_map = {r["status"]: r["cnt"] for r in status_df.to_dict("records")}
    stats = {
        "供应商": {"总数": n_suppliers, "状态分布": status_map},
        "供货合约": {"总数": n_contracts, "生效中": active_contracts},
        "合约年度总数": n_years,
        "条款明细": {"基础价格条款": n_pr, "阶梯返利条款": n_xol},
        "数据质量": {"联系电话为空的供应商数": n_empty_phone},
        "基础价格条款平均折扣率": avg_discount,
        "区域分布Top3": region_df.head(3).to_dict("records"),
        "品类分布Top3": category_df.head(3).to_dict("records"),
        "各采购年度合约年度数": year_df.to_dict("records"),
    }
    narrative = _narrative(api_key, stats)

    # ---- 组装 ----
    kpis = [
        ("供应商总数", n_suppliers, f"合作中 {status_map.get('合作中', 0)} · 考察期 {status_map.get('考察期', 0)}"),
        ("供货合约", n_contracts, f"生效中 {active_contracts}"),
        ("合约年度", n_years, "含补充协议"),
        ("条款明细", n_pr + n_xol, f"价格条款 {n_pr} · 返利条款 {n_xol}"),
        ("平均折扣率", f"{avg_discount * 100:.1f}%", "基础价格条款均值"),
        ("空电话供应商", n_empty_phone, "数据质量待补全"),
    ]
    kpi_html = "".join(
        f'<div class="kpi"><div class="name">{n}</div><div class="value">{v}</div><div class="sub">{s}</div></div>'
        for n, v, s in kpis
    )
    body = f"""
<section class="kpis">{kpi_html}</section>
<h2>一、区域与品类分布</h2>
<div class="charts">
  <div class="chart-card"><h3>供应商区域分布</h3>{_fig_html(_fig_bar(region_df, "region", "cnt"))}</div>
  <div class="chart-card"><h3>供应商品类分布 Top10</h3>{_fig_html(_fig_bar(category_df, "category", "cnt", "#7C9EF5"))}</div>
</div>
<h2>二、采购年度与供应商状态</h2>
<div class="charts">
  <div class="chart-card"><h3>各采购年度合约年度数</h3>{_fig_html(_fig_bar(year_df, "procurement_year", "cnt", "#52C41A"))}</div>
  <div class="chart-card"><h3>供应商状态分布</h3>{_fig_html(_fig_pie(status_df, "status", "cnt"))}</div>
</div>
<h2>三、阶梯返利条款 Top 10 供应商</h2>
{rebate_df.to_html(index=False, classes="data-table")}
<h2>四、数据质量：联系电话为空（Top 10）</h2>
{empty_df.to_html(index=False, classes="data-table")}
<h2>五、月度概览（AI 分析）</h2>
<div class="narrative">{_md(narrative)}</div>
"""
    footer = ("本报告由 AI Supplier Contract Assistant 自动生成（SQL 实时取数 + AI 撰写分析文字） ｜ "
              "演示数据为脚本生成的虚构数据，不含任何真实信息 ｜ 图表基于 Plotly，打开时需联网")
    return _page("供应商月度概况报告", f"生成时间：{now} ｜ 数据来源：供应商合约数据库（实时查询）", body, footer)


def qa_report_html(question, answer, df=None, chart=None):
    """把一轮问答导出为 HTML 报告（结论 + 数据表 + 图表）"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    body = f"<h2>问题</h2><p>{escape(question)}</p><h2>结论</h2>{_md(answer)}"
    if df is not None and not df.empty:
        body += f"<h2>数据明细（{len(df)} 行）</h2>{df.head(50).to_html(index=False, classes='data-table')}"
    if chart and df is not None:
        kind = chart.get("kind", "bar")
        if kind == "pie":
            fig = _fig_pie(df, chart["x"], chart["y"])
        elif kind == "line":
            fig = _style(go.Figure(go.Scatter(x=df[chart["x"]], y=df[chart["y"]], mode="lines+markers")))
        else:
            fig = _fig_bar(df, chart["x"], chart["y"])
        body += "<h2>图表</h2>" + _fig_html(fig)
    footer = "本报告由 AI Supplier Contract Assistant 自动生成 ｜ 演示数据为脚本生成的虚构数据，不含任何真实信息"
    return _page("问答报告", f"生成时间：{now}", body, footer)
