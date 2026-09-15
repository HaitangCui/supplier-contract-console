# -*- coding: utf-8 -*-
"""v3 报告生成冒烟测试

- 问答导出：本地构造数据验证 HTML 组装（不调 API）
- 模板月报：真实调用 DeepSeek 生成完整报告，并与直查数据库的数字交叉验证

运行：PYTHONIOENCODING=utf-8 python test_report.py
"""

import pandas as pd

from agent import get_api_key, run_sql
from report_gen import monthly_report_html, qa_report_html


def test_qa_export():
    df = pd.DataFrame({"region": ["华东", "华北"], "cnt": [9, 11]})
    html = qa_report_html(
        "各区域的供应商数量？", "华东 9 家、华北 11 家。", df, {"kind": "bar", "x": "region", "y": "cnt"}
    )
    for kw in ["各区域的供应商数量？", "华东 9 家", "数据明细", "plotly"]:
        assert kw in html, f"问答导出缺少内容：{kw}"
    print("QA export OK ✓")


def test_monthly_report():
    html = monthly_report_html(get_api_key())
    for kw in ["供应商月度概况报告", "月度概览", "plotly", "供应商总数", "区域分布", "返利条款", "数据质量",
               "供应商引入转化漏斗", "考察转合作率", "合作流失率"]:
        assert kw in html, f"月报缺少内容：{kw}"
    # 数字必须来自真实数据库：与直查结果交叉验证
    total = run_sql("SELECT COUNT(*) FROM suppliers").iloc[0, 0]
    assert str(total) in html, f"报告中找不到供应商总数 {total}（疑似编造）"
    # 漏斗数字与 supplier_events 流转表直查交叉验证
    entered = run_sql("SELECT COUNT(*) FROM supplier_events WHERE event_type = '转考察'").iloc[0, 0]
    joined = run_sql("SELECT COUNT(*) FROM supplier_events WHERE event_type = '转合作'").iloc[0, 0]
    lost = run_sql("SELECT COUNT(*) FROM supplier_events WHERE event_type = '终止合作'").iloc[0, 0]
    assert f"{joined / entered * 100:.1f}%" in html, "报告中考察转合作率与直查结果不一致"
    assert f"{lost / joined * 100:.1f}%" in html, "报告中合作流失率与直查结果不一致"
    print(f"Monthly report OK ✓ （供应商总数 {total}、漏斗 {entered}→{joined}→{joined - lost} 均与数据库一致）")


if __name__ == "__main__":
    test_qa_export()
    test_monthly_report()
    print("ALL REPORT TESTS PASSED ✓")
