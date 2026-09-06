# -*- coding: utf-8 -*-
"""AppTest 冒烟测试：完整跑一遍应用脚本 + 模拟新建供应商流程，断言无异常且数据入库。
测试直接在 console.db 上进行，结束后按名称清理测试数据（应用连接会锁文件，不做文件替换）。"""
import os
import sqlite3

from streamlit.testing.v1 import AppTest

ROOT = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(ROOT, "console.db")
TEST_NAME = "冒烟测试商贸有限公司"


def cleanup():
    conn = sqlite3.connect(DB)
    conn.execute("DELETE FROM suppliers WHERE supplier_name = ?", (TEST_NAME,))
    conn.commit()
    conn.close()


at = None
try:
    at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=60)
    at.run()
    assert not at.exception, str(at.exception)

    # 模拟新建供应商流程（覆盖：必填校验 + 重复检测 + 编号生成 + 入库）
    name_in = next(w for w in at.text_input if w.label == "供应商名称 *")
    name_in.set_value(TEST_NAME)
    btn = next(b for b in at.button if b.label == "创建供应商")
    btn.click()
    at.run()
    assert not at.exception, str(at.exception)

    # 直接查库验证（新建成功后脚本会 st.rerun()，成功提示不会留在最终状态里）
    conn = sqlite3.connect(DB)
    row = conn.execute("SELECT supplier_id FROM suppliers WHERE supplier_name = ?",
                       (TEST_NAME,)).fetchone()
    conn.close()
    assert row, "新建供应商未入库"
    print(f"SMOKE OK · 应用无异常，新建流程通过（生成编号 {row[0]}）")
finally:
    del at
    cleanup()
    print("测试数据已清理")
