# -*- coding: utf-8 -*-
"""AI Supplier Contract Assistant · Agent 核心（v2）

单 Agent + Tool Calling 循环：
    用户问题 → LLM → 调用工具（只读 SQL / 画图）→ 结果回传 → LLM 总结
安全边界：
    - SQL 仅允许 SELECT（关键词过滤 + SELECT 前缀 + 表白名单 + 只读连接，四层防御）
    - 写操作（编辑/删除）不在 Agent 工具范围内，仍由 v1 人工执行（乐观锁 + 二次确认）
"""

import json
import os
import re
import sqlite3

import pandas as pd
from openai import OpenAI

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "console.db")
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
MODEL = "deepseek-chat"
MAX_TOOL_ROUNDS = 8
MAX_ROWS = 200

ALLOWED_TABLES = {"suppliers", "contracts", "contract_years", "split_details_pr", "split_details_xol", "supplier_events"}
FORBIDDEN_KEYWORDS = (
    "insert", "update", "delete", "drop", "alter", "create", "replace",
    "attach", "detach", "pragma", "vacuum", "transaction", "grant", "revoke",
)

with open(SCHEMA_PATH, encoding="utf-8") as f:
    SCHEMA_TEXT = f.read()

SYSTEM_PROMPT = f"""你是「供应商合约数据助手」，服务供应链采购团队，回答关于供货合约数据的问题。

数据在 SQLite 数据库中（只读），5 张核心合约表 + 1 张供应商生命周期事件表（关系模型如下）：
{SCHEMA_TEXT}

规则：
1. 所有数字必须来自 SQL 查询结果，禁止心算或编造
2. 不确定字段时，先执行 SELECT * FROM 表名 LIMIT 3 查看真实列名
3. 单次查询最多返回 {MAX_ROWS} 行，取 TOP N 时用 ORDER BY + LIMIT
4. 用简体中文回答：先给结论，再给关键依据，简洁，不要罗列 SQL
5. 问题无法用现有数据回答时，说明缺少什么数据，不要硬答
6. 结果适合可视化时调用 make_chart 画图（柱状图 bar / 折线图 line / 饼图 pie）

示例：
问：哪些供应商的联系电话是空的？
[调用 sql_query: SELECT supplier_name, region FROM suppliers WHERE contact_phone IS NULL OR contact_phone = '']
答：共 X 家供应商未登记联系电话，其中华东 X 家、华北 X 家……

问：各区域的供应商数量分布，画个柱状图
[调用 sql_query: SELECT region, COUNT(*) AS cnt FROM suppliers GROUP BY region]
[调用 make_chart: x_column=region, y_column=cnt, kind=bar]
答：东北 X 家、西北 X 家……（附柱状图）
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "sql_query",
            "description": "对数据库执行只读 SQL 查询（仅 SELECT）。用于查数、聚合、分组、多表 JOIN、对比等一切取数需求。",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "只读 SELECT 语句，可含 JOIN/GROUP BY/ORDER BY/LIMIT"}
                },
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "make_chart",
            "description": "把最近一次查询结果画成图表。x_column 为分类列，y_column 为数值列。kind 可选 bar/line/pie。",
            "parameters": {
                "type": "object",
                "properties": {
                    "x_column": {"type": "string", "description": "分类列名（横轴/分类）"},
                    "y_column": {"type": "string", "description": "数值列名（纵轴/数值）"},
                    "kind": {"type": "string", "enum": ["bar", "line", "pie"]},
                },
                "required": ["x_column", "y_column", "kind"],
            },
        },
    },
]


def get_api_key():
    """读取 DeepSeek API Key：环境变量 → 本地 .streamlit/secrets.toml"""
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key:
        return key
    secrets_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".streamlit", "secrets.toml")
    if os.path.exists(secrets_path):
        try:
            import tomllib  # Python 3.11+
            with open(secrets_path, "rb") as f:
                return tomllib.load(f).get("DEEPSEEK_API_KEY", "")
        except Exception:
            text = open(secrets_path, encoding="utf-8").read()
            m = re.search(r'DEEPSEEK_API_KEY\s*=\s*"([^"]+)"', text)
            if m:
                return m.group(1)
    return ""


def _validate_select(sql):
    """SELECT-only 校验：关键词过滤 + 前缀检查 + 表白名单"""
    low = sql.strip().lower().rstrip(";")
    if not low:
        return "SQL 为空"
    if not (low.startswith("select") or low.startswith("with")):
        return "仅允许只读 SELECT 查询"
    for kw in FORBIDDEN_KEYWORDS:
        if kw in low:
            return f"检测到禁止的关键词 {kw}，仅允许只读 SELECT 查询"
    for name in re.findall(r"(?:from|join)\s+([a-z_][a-z0-9_]*)", low):
        if name not in ALLOWED_TABLES:
            return f"不允许访问表 {name}（白名单之外）"
    return None


def run_sql(sql):
    """执行一条只读 SELECT 并返回 DataFrame（报告生成等场景复用；防护与 sql_query 工具相同）"""
    err = _validate_select(sql)
    if err:
        raise ValueError(err)
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        cur = conn.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchmany(MAX_ROWS + 1)
        if cols:
            return pd.DataFrame(rows[:MAX_ROWS], columns=cols)
        return pd.DataFrame()
    finally:
        conn.close()


def _execute_tool(name, args, state):
    if name == "sql_query":
        sql = str(args.get("sql", ""))
        err = _validate_select(sql)
        if err:
            return {"error": err}
        try:
            # 只读连接（file:...?mode=ro），即使校验被绕过也无法写库
            conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
            cur = conn.execute(sql)
            cols = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchmany(MAX_ROWS + 1)
            conn.close()
            truncated = len(rows) > MAX_ROWS
            rows = rows[:MAX_ROWS]
            if cols:
                df = pd.DataFrame(rows, columns=cols)
                state["last_df"] = df
            return {
                "columns": cols,
                "rows": [list(r) for r in rows],
                "truncated": truncated,
                "note": "查询成功，结果将展示为表格",
            }
        except sqlite3.Error as e:
            return {"error": f"SQL 执行失败：{e}。请检查 SQL 后重试。"}

    if name == "make_chart":
        if state.get("last_df") is None:
            return {"error": "还没有查询结果，请先调用 sql_query 取数"}
        df = state["last_df"]
        x, y = str(args.get("x_column", "")), str(args.get("y_column", ""))
        kind = args.get("kind", "bar")
        if x not in df.columns or y not in df.columns:
            return {"error": f"列不存在。可用列：{list(df.columns)}"}
        df[y] = pd.to_numeric(df[y], errors="coerce")
        state["chart"] = {"kind": kind, "x": x, "y": y}
        return {"ok": True, "kind": kind, "x": x, "y": y, "note": f"已生成{kind}图：{x} → {y}"}

    return {"error": f"未知工具 {name}"}


def run_agent(question, history=None, api_key=None):
    """执行一轮 Agent 对话。返回 {answer, df, chart, rounds}"""
    key = api_key or get_api_key()
    if not key:
        raise RuntimeError(
            "未配置 DEEPSEEK_API_KEY：本地请在 .streamlit/secrets.toml 中填写，"
            "云端请在 Streamlit Cloud → App Settings → Secrets 中填写"
        )
    # timeout=60 + max_retries=0：单次调用最多 60s 即报错，避免公开部署时请求卡死无输出
    client = OpenAI(api_key=key, base_url="https://api.deepseek.com", timeout=60, max_retries=0)
    state = {"last_df": None, "chart": None}

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in history or []:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": question})

    rounds = 0
    for _ in range(MAX_TOOL_ROUNDS):
        rounds += 1
        resp = client.chat.completions.create(
            model=MODEL, messages=messages, tools=TOOLS, tool_choice="auto", temperature=0.3
        )
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))
        if not msg.tool_calls:
            return {"answer": msg.content or "", "df": state["last_df"], "chart": state["chart"], "rounds": rounds}
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                result = {"error": "工具参数不是合法 JSON"}
            else:
                result = _execute_tool(tc.function.name, args, state)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result, ensure_ascii=False)})
    return {"answer": "（分析步骤过多，已超过最大工具轮次，请换个问法）", "df": state["last_df"], "chart": state["chart"], "rounds": rounds}
