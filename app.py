# -*- coding: utf-8 -*-
"""Supplier Contract Console · 供货合约管理台（Streamlit 应用）
五大模块：
  📊 总览 —— 核心指标与分布看板
  🔍 查询 —— 供应商→合约→年度→条款 级联下钻，四种空统一展示，CSV 导出
  ✏️ 编辑 —— 快照 + 乐观锁并发防护（可模拟并发冲突），批量修改 + 事务回滚演示
  ➕ 新建 —— 五层实体逐层新建，字段校验 + 重复检测，编号系统生成
  🗑️ 删除 —— 影响预览 + 二次确认 + 级联清理（单事务）
设计来源：供应链合约数据维护的产品需求（虚构业务场景），演示数据 100% 虚构。
"""
import datetime as dt
import random

import pandas as pd
import streamlit as st

import db

st.set_page_config(page_title="供货合约管理台 · Supplier Contract Console",
                   page_icon="📦", layout="wide")

# ---------- 选项常量 ----------
PAYMENT_OPTIONS = ["月结30天", "月结45天", "月结60天", "现结", "预付30%+月结"]
DELIVERY_OPTIONS = ["次日达", "隔日达", "每周2次配送", "每周3次配送", "产地直发"]
SKU_OPTIONS = ["叶菜类", "根茎类", "猪肉", "禽肉", "海鲜冻品", "食用油", "调味品",
               "啤酒", "饮料", "纸箱", "保温箱", "冰袋", "干线运输", "城市配送"]
REGION_OPTIONS = ["华东", "华北", "华南", "华中", "西南", "西北", "东北"]
CATEGORY_OPTIONS = ["生鲜果蔬", "肉禽冻品", "粮油调味", "酒水饮料", "包装耗材", "冷链物流"]
SUPPLIER_STATUS = ["合作中", "考察期", "已终止"]
CONTRACT_TYPE = ["框架协议", "单次供货"]
CONTRACT_STATUS = ["生效中", "已到期", "草稿", "已终止"]


def pct(v, nd=0):
    return f"{v * 100:.{nd}f}%"


# ---------- 展示用 DataFrame 构造 ----------

def df_suppliers(rows):
    return pd.DataFrame([{
        "编号": r["supplier_id"], "名称": r["supplier_name"], "区域": r["region"],
        "品类": r["category"], "联系人": db.fmt(r["contact_person"]),
        "电话": db.fmt(r["contact_phone"]), "状态": r["status"],
        "建档日期": r["created_at"][:10],
    } for r in rows])


def df_contracts(rows):
    return pd.DataFrame([{
        "编号": r["contract_id"], "合约编号": r["contract_no"], "名称": r["contract_name"],
        "类型": r["contract_type"], "状态": r["status"],
        "签订日期": db.fmt(r["signed_date"])[:10] if r["signed_date"] else db.EMPTY,
        "生效日期": r["valid_from"][:10], "到期日期": r["valid_to"][:10],
        "备注": db.fmt(r["note"]),
    } for r in rows])


def df_years(rows):
    return pd.DataFrame([{
        "编号": r["contract_year_id"], "采购年度": r["procurement_year"],
        "补充协议": "是" if r["is_supplementary"] else "否",
        "账期条款": r["payment_terms"], "交付条款": db.fmt(r["delivery_terms"]),
        "备注": db.fmt(r["note"]),
    } for r in rows])


def df_pr(rows):
    return pd.DataFrame([{
        "编号": r["pr_detail_id"], "物料品类": r["sku_category"],
        "基础折扣率": pct(r["base_discount_rate"]),
        "结算周期": r["settlement_cycle"], "备注": db.fmt(r["note"]),
    } for r in rows])


def df_xol(rows):
    return pd.DataFrame([{
        "编号": r["xol_detail_id"], "物料品类": r["sku_category"],
        "起返采购量(件)": int(r["volume_threshold"]),
        "返利比例": pct(r["rebate_rate"], 1),
        "返利封顶(元)": "不封顶" if r["rebate_cap"] is None else int(r["rebate_cap"]),
        "备注": db.fmt(r["note"]),
    } for r in rows])


def level_df(level, rows):
    """编辑/删除页的层级列表（含版本号）"""
    if level == "供应商":
        return pd.DataFrame([{"编号": r["id"], "名称": r["name"], "状态": r["status"],
                              "联系人": db.fmt(r["contact_person"]), "版本": f"v{r['version']}"} for r in rows])
    if level == "供货合约":
        return pd.DataFrame([{"编号": r["id"], "合约编号": r["contract_no"], "名称": r["name"],
                              "供应商": r["supplier_name"], "状态": r["status"],
                              "版本": f"v{r['version']}"} for r in rows])
    if level == "合约年度":
        return pd.DataFrame([{"编号": r["id"], "合约编号": r["contract_no"],
                              "采购年度": r["procurement_year"],
                              "补充协议": "是" if r["is_supplementary"] else "否",
                              "账期条款": r["payment_terms"], "版本": f"v{r['version']}"} for r in rows])
    if level == "基础价格条款":
        return pd.DataFrame([{"编号": r["id"], "合约编号": r["contract_no"],
                              "物料品类": r["sku_category"],
                              "基础折扣率": pct(r["base_discount_rate"]),
                              "版本": f"v{r['version']}"} for r in rows])
    return pd.DataFrame([{"编号": r["id"], "合约编号": r["contract_no"],
                          "物料品类": r["sku_category"],
                          "起返采购量(件)": int(r["volume_threshold"]),
                          "版本": f"v{r['version']}"} for r in rows])


def _pick(df, ev):
    """从 st.dataframe 单选事件中取出选中行的「编号」（主键）"""
    sel = getattr(ev, "selection", None)
    if sel is None or not sel.rows:
        return None
    idx = sel.rows[0]
    return df.iloc[idx]["编号"] if idx < len(df) else None


# ---------- 📊 总览 ----------

def tab_overview(conn):
    s = db.stats(conn)
    m = st.columns(5)
    m[0].metric("供应商", s["suppliers"])
    m[1].metric("供货合约", s["contracts"])
    m[2].metric("合约年度", s["years"])
    m[3].metric("基础价格条款", s["pr"])
    m[4].metric("阶梯返利条款", s["xol"])

    st.markdown("---")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**供应商区域分布**")
        st.bar_chart(pd.DataFrame({"数量": list(db.group_counts(conn, "suppliers", "region").values())},
                                  index=list(db.group_counts(conn, "suppliers", "region").keys())))
    with c2:
        st.markdown("**供应品类分布**")
        st.bar_chart(pd.DataFrame({"数量": list(db.group_counts(conn, "suppliers", "category").values())},
                                  index=list(db.group_counts(conn, "suppliers", "category").keys())))
    with c3:
        st.markdown("**合约状态分布**")
        st.bar_chart(pd.DataFrame({"数量": list(db.group_counts(conn, "contracts", "status").values())},
                                  index=list(db.group_counts(conn, "contracts", "status").keys())))
    st.caption("演示数据由脚本随机生成（随机种子 2026），不含任何真实企业信息。")


# ---------- 🔍 查询 ----------

def tab_query(conn):
    st.subheader("级联查询：供应商 → 供货合约 → 合约年度 → 条款明细")
    f1, f2, f3, f4 = st.columns(4)
    region = f1.selectbox("区域", ["全部"] + REGION_OPTIONS, key="q_region")
    category = f2.selectbox("品类", ["全部"] + CATEGORY_OPTIONS, key="q_cat")
    status = f3.selectbox("供应商状态", ["全部"] + SUPPLIER_STATUS, key="q_status")
    kw = f4.text_input("名称关键词", key="q_kw")

    s_rows = db.list_suppliers(conn, None if region == "全部" else region,
                               None if category == "全部" else category,
                               None if status == "全部" else status, kw or None)
    s_df = df_suppliers(s_rows)
    st.caption(f"供应商 {len(s_rows)} 条 · 点击行下钻；空值统一显示为「{db.EMPTY}」")
    ev_s = st.dataframe(s_df, key="q_s", on_select="rerun", selection_mode="single-row",
                        hide_index=True, width="stretch", height=240)
    sid = _pick(s_df, ev_s)
    if not sid:
        return

    c_rows = db.list_contracts(conn, sid)
    c_df = df_contracts(c_rows)
    st.markdown(f"**{sid} 的供货合约（{len(c_rows)} 条）**")
    st.download_button("⬇ 导出该供应商合约 CSV", c_df.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"{sid}_contracts.csv", key="q_dl_c")
    ev_c = st.dataframe(c_df, key="q_c", on_select="rerun", selection_mode="single-row",
                        hide_index=True, width="stretch", height=220)
    cid = _pick(c_df, ev_c)
    if not cid:
        return

    y_rows = db.list_years(conn, cid)
    y_df = df_years(y_rows)
    st.markdown(f"**{cid} 的合约年度（{len(y_rows)} 条）**")
    ev_y = st.dataframe(y_df, key="q_y", on_select="rerun", selection_mode="single-row",
                        hide_index=True, width="stretch", height=200)
    yid = _pick(y_df, ev_y)
    if not yid:
        return

    d1, d2 = st.columns(2)
    with d1:
        st.markdown(f"**{yid} · 基础价格条款（{len(db.list_pr(conn, yid))} 条）**")
        st.dataframe(df_pr(db.list_pr(conn, yid)), hide_index=True, width="stretch")
    with d2:
        st.markdown(f"**{yid} · 阶梯返利条款（{len(db.list_xol(conn, yid))} 条）**")
        st.dataframe(df_xol(db.list_xol(conn, yid)), hide_index=True, width="stretch")


# ---------- ✏️ 编辑 ----------

EDIT_CONF = {
    "供应商": {
        "fields": [
            ("status", "状态", "select", SUPPLIER_STATUS),
            ("contact_person", "联系人", "text", None),
            ("contact_phone", "联系电话", "text", None),
        ],
    },
    "供货合约": {
        "fields": [
            ("contract_name", "合约名称", "text", None),
            ("status", "状态", "select", CONTRACT_STATUS),
            ("valid_from", "生效日期", "date", None),
            ("valid_to", "到期日期", "date", None),
            ("note", "备注", "text", None),
        ],
        "required": ["valid_from", "valid_to"],
    },
    "合约年度": {
        "fields": [
            ("payment_terms", "账期条款", "select", PAYMENT_OPTIONS),
            ("delivery_terms", "交付条款", "select", ["（空）"] + DELIVERY_OPTIONS),
            ("is_supplementary", "是否补充协议", "check", None),
            ("note", "备注", "text", None),
        ],
    },
    "基础价格条款": {
        "fields": [
            ("base_discount_rate", "基础折扣率", "number", (0.01, 1.0, 0.01)),
            ("settlement_cycle", "结算周期", "select", ["月结", "季结", "半年结"]),
            ("note", "备注", "text", None),
        ],
    },
    "阶梯返利条款": {
        "fields": [
            ("volume_threshold", "起返采购量（件）", "number", (1000, 1000000, 1000)),
            ("rebate_rate", "返利比例", "number", (0.001, 0.2, 0.001)),
            ("rebate_cap", "返利封顶（元，0=不封顶）", "number", (0, 10000000, 1000)),
            ("note", "备注", "text", None),
        ],
    },
}


def _widget(col, label, kind, opts, row):
    """按字段类型生成表单控件，默认值来自快照行"""
    v = row.get(col)
    if kind == "select":
        idx = opts.index(v) if v in opts else 0
        return st.selectbox(label, opts, index=idx, key="e_" + col)
    if kind == "text":
        return st.text_input(label, value="" if v is None else str(v), key="e_" + col)
    if kind == "date":
        dval = dt.date.fromisoformat(str(v)[:10]) if v else None
        return st.date_input(label, value=dval, key="e_" + col)
    if kind == "number":
        lo, hi, step = opts
        return st.number_input(label, min_value=lo, max_value=hi, step=step,
                               value=float(v if v is not None else lo), key="e_" + col)
    return st.checkbox(label, value=bool(v), key="e_" + col)


def tab_edit(conn):
    st.subheader("编辑：快照 + 乐观锁并发防护")
    st.caption("机制：进入编辑时记录「快照版本」→ 保存时比对数据库当前版本 → 不一致则拦截后保存者。"
               "可点击「模拟另一用户修改」演示冲突拦截。")
    level = st.radio("选择层级", list(EDIT_CONF.keys()), horizontal=True, key="e_level")
    table, pk_col = db.level_table(level)

    rows = db.list_level(conn, level)
    if not rows:
        st.info("该层级暂无数据。")
        return
    df = level_df(level, rows)
    ev = st.dataframe(df, key="e_sel", on_select="rerun", selection_mode="single-row",
                      hide_index=True, width="stretch", height=230)
    pk = _pick(df, ev)
    if not pk:
        st.info("点击上方一行开始编辑。")
        return

    # 快照：仅在层级/选中行变化时重新加载
    snap = st.session_state.get("edit_snap")
    if not snap or snap["level"] != level or snap["pk"] != pk:
        full = db.fetch_row(conn, table, pk_col, pk)
        snap = {"level": level, "pk": pk, "version": full["version"], "row": dict(full)}
        st.session_state["edit_snap"] = snap

    live = db.fetch_row(conn, table, pk_col, pk)
    if live is None:
        st.warning("该记录已不存在，请刷新。")
        return
    if live["version"] == snap["version"]:
        st.caption(f"快照版本 v{snap['version']} ｜ 数据库当前版本 v{live['version']} ｜ 一致 ✅")
    else:
        st.caption(f"快照版本 v{snap['version']} ｜ 数据库当前版本 v{live['version']} ｜ 不一致 ⚠️")

    conf = EDIT_CONF[level]
    with st.form("edit_form"):
        vals = {}
        for col, label, kind, opts in conf["fields"]:
            vals[col] = _widget(col, label, kind, opts, snap["row"])
        submitted = st.form_submit_button("保存修改", type="primary")

    if submitted:
        errors = []
        for col, label, kind, _ in conf["fields"]:
            val = vals[col]
            if kind == "date":
                val = None if val is None else val.isoformat()
            if kind == "check":
                val = 1 if val else 0
            if kind == "select" and val == "（空）":
                val = None
            if val in (None, "") and col in conf.get("required", []):
                errors.append(f"「{label}」为必填项")
            vals[col] = val
        if level == "供货合约" and vals["valid_from"] and vals["valid_to"] \
                and vals["valid_from"] > vals["valid_to"]:
            errors.append("「生效日期」不能晚于「到期日期」")
        if not errors:
            try:
                old, new = snap["version"], db.optimistic_update(
                    conn, table, pk_col, pk, snap["version"], vals)
                st.success(f"✅ 保存成功：版本 v{old} → v{new}")
                snap["version"] = new
                snap["row"].update(vals)
            except db.ConflictError as e:
                st.error(str(e))
                if st.button("🔄 加载最新数据并重新编辑", key="e_reload"):
                    st.session_state.pop("edit_snap", None)
                    st.rerun()
        else:
            for e in errors:
                st.error(e)

    # 模拟并发修改（表单外）：直接改库版本号，演示乐观锁拦截
    if st.button("⚡ 模拟另一用户修改（该行版本 +1）", key="e_sim"):
        now = dt.datetime.now().isoformat(timespec="seconds")
        conn.execute(f"UPDATE {table} SET version = version + 1, updated_at = ? "
                     f"WHERE {pk_col} = ?", (now, pk))
        conn.commit()
        st.warning("已模拟：数据库版本已 +1。此时点击表单里的「保存修改」将被乐观锁拦截。")

    # 批量修改 + 事务回滚演示
    st.markdown("---")
    st.subheader("批量修改 + 事务回滚（演示）")
    c_rows = db.list_contracts(conn)
    if c_rows:
        opt = {f"{r['contract_no']}｜{r['contract_name']}（{r['supplier_name']}）": r["contract_id"]
               for r in c_rows}
        target = st.selectbox("选择合约", list(opt.keys()), key="e_batch_c")
        new_terms = st.selectbox("新账期条款（应用到该合约全部年度）",
                                 PAYMENT_OPTIONS, key="e_batch_t")
        if st.button("🚀 批量应用（单事务）", key="e_batch_go"):
            backup = db.batch_update_years(conn, opt[target], new_terms)
            st.session_state["batch_backup"] = backup
            st.success(f"✅ 已批量更新 {len(backup)} 个年度（单个事务提交），可随时整体回滚。")
        if st.session_state.get("batch_backup") and st.button("↩ 回滚本次批量修改", key="e_batch_rollback"):
            db.rollback_batch(conn, st.session_state.pop("batch_backup"))
            st.success("✅ 已按备份整体回滚（单事务），数据恢复原状。")


# ---------- ➕ 新建 ----------

def _make_contract_no(conn):
    """合约编号自动建议：随机生成并保证不重复（可手动修改）"""
    while True:
        no = f"CT{dt.date.today().year}{random.randint(10000, 99999)}"
        if not db.dup_check(conn, "contracts", "contract_no", no):
            return no


def tab_create(conn):
    st.subheader("新建：字段校验 + 重复检测")
    st.caption("编号由系统自动生成（如 S0001、C0001），用户不可编辑——与真实工具的产品设计一致。")

    # ① 供应商
    with st.expander("① 新建供应商", expanded=True):
        with st.form("f_supplier"):
            c1, c2 = st.columns(2)
            name = c1.text_input("供应商名称 *", key="crs_name")
            region = c1.selectbox("区域", REGION_OPTIONS, key="crs_region")
            category = c2.selectbox("供应品类", CATEGORY_OPTIONS, key="crs_category")
            status = c2.selectbox("状态", SUPPLIER_STATUS, key="crs_status")
            contact = c1.text_input("联系人", key="crs_contact")
            phone = c2.text_input("联系电话", key="crs_phone")
            ok = st.form_submit_button("创建供应商", type="primary")
        if ok:
            if not name.strip():
                st.error("「供应商名称」为必填项")
            elif db.dup_check(conn, "suppliers", "supplier_name", name.strip()):
                st.error(f"重复检测：供应商「{name.strip()}」已存在，请勿重复创建。")
            else:
                sid = db.next_id(conn, "suppliers", "supplier_id", "S", 4)
                conn.execute(
                    "INSERT INTO suppliers (supplier_id, supplier_name, region, category, "
                    "contact_person, contact_phone, status, created_at, version) "
                    "VALUES (?,?,?,?,?,?,?,?,1)",
                    (sid, name.strip(), region, category, contact or None, phone or None,
                     status, dt.date.today().isoformat()))
                conn.commit()
                st.success(f"✅ 已创建供应商 {sid} · {name.strip()}")
                st.rerun()

    # ② 供货合约
    with st.expander("② 新建供货合约"):
        s_rows = db.list_suppliers(conn)
        if not s_rows:
            st.info("请先创建供应商。")
        else:
            with st.form("f_contract"):
                if "c_no_sugg" not in st.session_state:
                    st.session_state["c_no_sugg"] = _make_contract_no(conn)
                c1, c2 = st.columns(2)
                supplier = c1.selectbox(
                    "供应商", [f"{r['supplier_id']}｜{r['supplier_name']}" for r in s_rows],
                    key="crc_supplier")
                ctype = c1.selectbox("合约类型", CONTRACT_TYPE, key="crc_type")
                status = c2.selectbox("状态", CONTRACT_STATUS, key="crc_status")
                name = c2.text_input("合约名称 *", key="crc_name")
                cno = c1.text_input("合约编号（自动建议，可修改）",
                                    value=st.session_state["c_no_sugg"], key="crc_no")
                sd = c2.date_input("签订日期（可空）", value=None, key="crc_signed")
                c3, c4 = st.columns(2)
                vf = c3.date_input("生效日期 *", value=dt.date.today(), key="crc_vf")
                vt = c4.date_input("到期日期 *",
                                   value=dt.date.today() + dt.timedelta(days=365), key="crc_vt")
                note = st.text_input("备注", key="crc_note")
                ok = st.form_submit_button("创建合约", type="primary")
            if ok:
                if not name.strip():
                    st.error("「合约名称」为必填项")
                elif vf > vt:
                    st.error("「生效日期」不能晚于「到期日期」")
                elif db.dup_check(conn, "contracts", "contract_no", cno.strip()):
                    st.error(f"重复检测：合约编号「{cno.strip()}」已存在，请修改后重试。")
                else:
                    cid = db.next_id(conn, "contracts", "contract_id", "C", 4)
                    conn.execute(
                        "INSERT INTO contracts (contract_id, supplier_id, contract_no, contract_name, "
                        "contract_type, status, signed_date, valid_from, valid_to, note, version) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,1)",
                        (cid, supplier.split("｜")[0], cno.strip(), name.strip(), ctype, status,
                         sd.isoformat() if sd else None, vf.isoformat(), vt.isoformat(),
                         note or None))
                    conn.commit()
                    st.success(f"✅ 已创建供货合约 {cid} · {cno.strip()}")
                    st.session_state.pop("c_no_sugg", None)
                    st.rerun()

    # ③ 合约年度
    with st.expander("③ 新建合约年度"):
        c_rows = db.list_contracts(conn)
        if not c_rows:
            st.info("请先创建供货合约。")
        else:
            with st.form("f_year"):
                c1, c2 = st.columns(2)
                contract = c1.selectbox(
                    "所属合约", [f"{r['contract_id']}｜{r['contract_no']}｜{r['contract_name']}"
                                 for r in c_rows], key="cry_contract")
                pyear = c1.number_input("采购年度", min_value=2024, max_value=2030,
                                        value=2026, step=1, key="cry_year")
                is_supp = c2.checkbox("是否补充协议", key="cry_supp")
                pt = c2.selectbox("账期条款", PAYMENT_OPTIONS, key="cry_pt")
                dtm = st.selectbox("交付条款", ["（空）"] + DELIVERY_OPTIONS, key="cry_dt")
                note = st.text_input("备注", key="cry_note")
                ok = st.form_submit_button("创建合约年度", type="primary")
            if ok:
                cid = contract.split("｜")[0]
                dup = conn.execute(
                    "SELECT 1 FROM contract_years WHERE contract_id = ? AND procurement_year = ? "
                    "AND is_supplementary = ?", (cid, int(pyear), 1 if is_supp else 0)).fetchone()
                if dup:
                    st.error(f"重复检测：合约 {cid} 的 {int(pyear)} 年度已存在相同协议类型的记录。"
                             "如需加签请勾选「补充协议」。")
                else:
                    yid = db.next_id(conn, "contract_years", "contract_year_id", "CY", 5)
                    conn.execute(
                        "INSERT INTO contract_years (contract_year_id, contract_id, procurement_year, "
                        "is_supplementary, payment_terms, delivery_terms, note, version) "
                        "VALUES (?,?,?,?,?,?,?,1)",
                        (yid, cid, int(pyear), 1 if is_supp else 0, pt,
                         None if dtm == "（空）" else dtm, note or None))
                    conn.commit()
                    st.success(f"✅ 已创建合约年度 {yid}")
                    st.rerun()

    # ④ 价格条款 / ⑤ 返利条款
    y_rows = db.list_all_years(conn)
    if not y_rows:
        st.info("④⑤ 需先创建合约年度。")
        return

    year_opt = {f"{y['contract_year_id']}｜{y['procurement_year']}年度｜"
                f"{'补充协议' if y['is_supplementary'] else '主协议'}": y["contract_year_id"]
                for y in y_rows}

    with st.expander("④ 新建基础价格条款"):
        with st.form("f_pr"):
            c1, c2 = st.columns(2)
            year = c1.selectbox("所属合约年度", list(year_opt.keys()), key="crp_year")
            sku = c1.selectbox("物料品类", SKU_OPTIONS, key="crp_sku")
            rate = c2.number_input("基础折扣率", min_value=0.01, max_value=1.0,
                                   value=0.92, step=0.01, format="%.2f", key="crp_rate")
            cycle = c2.selectbox("结算周期", ["月结", "季结", "半年结"], key="crp_cycle")
            note = st.text_input("备注", key="crp_note")
            ok = st.form_submit_button("创建价格条款", type="primary")
        if ok:
            pid = db.next_id(conn, "split_details_pr", "pr_detail_id", "PR", 5)
            conn.execute(
                "INSERT INTO split_details_pr (pr_detail_id, contract_year_id, sku_category, "
                "base_discount_rate, settlement_cycle, note, version) VALUES (?,?,?,?,?,?,1)",
                (pid, year_opt[year], sku, float(rate), cycle, note or None))
            conn.commit()
            st.success(f"✅ 已创建价格条款 {pid}")
            st.rerun()

    with st.expander("⑤ 新建阶梯返利条款"):
        with st.form("f_xol"):
            c1, c2 = st.columns(2)
            year = c1.selectbox("所属合约年度", list(year_opt.keys()), key="crx_year")
            sku = c1.selectbox("物料品类", SKU_OPTIONS, key="crx_sku")
            threshold = c2.number_input("起返采购量（件）", min_value=1000, max_value=1000000,
                                        value=10000, step=1000, key="crx_threshold")
            rate = c2.number_input("返利比例", min_value=0.001, max_value=0.2,
                                   value=0.05, step=0.001, format="%.3f", key="crx_rate")
            cap = st.number_input("返利封顶（元，0=不封顶）", min_value=0, max_value=10000000,
                                  value=0, step=1000, key="crx_cap")
            note = st.text_input("备注", key="crx_note")
            ok = st.form_submit_button("创建返利条款", type="primary")
        if ok:
            xid = db.next_id(conn, "split_details_xol", "xol_detail_id", "XO", 5)
            conn.execute(
                "INSERT INTO split_details_xol (xol_detail_id, contract_year_id, sku_category, "
                "volume_threshold, rebate_rate, rebate_cap, note, version) VALUES (?,?,?,?,?,?,?,1)",
                (xid, year_opt[year], sku, float(threshold), float(rate),
                 float(cap) if cap > 0 else None, note or None))
            conn.commit()
            st.success(f"✅ 已创建返利条款 {xid}")
            st.rerun()


# ---------- 🗑️ 删除 ----------

def tab_delete(conn):
    st.subheader("删除：影响预览 + 二次确认 + 级联清理")
    level = st.radio("删除层级", ["供应商", "供货合约", "合约年度"], horizontal=True, key="d_level")
    rows = db.list_level(conn, level)
    if not rows:
        st.info("该层级暂无数据。")
        return
    df = level_df(level, rows)
    ev = st.dataframe(df, key="d_sel", on_select="rerun", selection_mode="single-row",
                      hide_index=True, width="stretch", height=230)
    pk = _pick(df, ev)
    if not pk:
        st.info("点击上方一行查看删除影响。")
        return

    impacts = db.impact_preview(conn, level, pk)
    st.warning("⚠️ 级联影响预览（本次删除将一并移除，单事务执行）：\n\n" +
               "\n".join(f"- {x}" for x in impacts))
    c1, c2 = st.columns([3, 1])
    confirm = c1.checkbox("我已阅读以上影响，确认执行删除", key="d_confirm")
    if c2.button("🗑 执行删除", type="primary", disabled=not confirm, key="d_go"):
        db.delete_cascade(conn, level, pk)
        st.success("✅ 已级联删除，事务提交成功。")
        st.rerun()


# ---------- 入口 ----------

conn = db.get_conn()

st.sidebar.title("📦 供货合约管理台")
st.sidebar.caption("Supplier Contract Console")
st.sidebar.markdown(
    "**设计来源**：供应链合约数据维护的产品需求（虚构业务场景），"
    "用于演示产品机制与工程实现。\n\n"
    "**核心机制**：乐观锁并发防护 · 事务回滚 · 级联删除 · 重复检测 · 四种空统一展示")
st.sidebar.info("演示数据为脚本随机生成的虚构数据，不含任何真实企业信息。")
st.sidebar.markdown("**本地运行**\n```\nstreamlit run app.py\n```")

st.title("📦 供货合约管理台")
st.caption("供应链采购合约数据维护工具 · 演示数据 1,200 条合约 / 80 家供应商（虚构）")

tabs = st.tabs(["📊 总览", "🔍 查询", "✏️ 编辑", "➕ 新建", "🗑️ 删除"])
with tabs[0]:
    tab_overview(conn)
with tabs[1]:
    tab_query(conn)
with tabs[2]:
    tab_edit(conn)
with tabs[3]:
    tab_create(conn)
with tabs[4]:
    tab_delete(conn)
