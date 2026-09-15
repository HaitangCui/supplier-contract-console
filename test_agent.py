# -*- coding: utf-8 -*-
"""Agent 冒烟测试：golden questions 直连 DeepSeek 验证（不依赖 Streamlit）

运行：PYTHONIOENCODING=utf-8 python test_agent.py
"""

from agent import get_api_key, run_agent

GOLDEN = [
    "哪些供应商的联系电话是空的？",
    "各区域的供应商数量分布，画个柱状图",
    "2026 采购年度的合约年度有多少份？和 2025 年对比一下",
]


def main():
    key = get_api_key()
    assert key, "未找到 DEEPSEEK_API_KEY（请在 .streamlit/secrets.toml 填写）"
    for q in GOLDEN:
        print("=" * 60)
        print("问:", q)
        r = run_agent(q, api_key=key)
        print("轮次:", r["rounds"], "| 图表:", r["chart"] or "无")
        if r["df"] is not None:
            print("数据:", len(r["df"]), "行 x", len(r["df"].columns), "列")
            print(r["df"].head(5).to_string())
        print("答:", r["answer"])
        assert r["answer"], "answer 为空"
    print("=" * 60)
    print("ALL GOLDEN QUESTIONS PASSED ✓")


if __name__ == "__main__":
    main()
