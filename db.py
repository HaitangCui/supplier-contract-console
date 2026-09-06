# -*- coding: utf-8 -*-
"""Supplier Contract Console · 数据访问层
SQLite 连接 / 四种空统一展示 / 通用查询 / 乐观锁保存 / 事务回滚 / 级联删除。
"""
import os
import sqlite3
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "console.db")

EMPTY = "—"


class ConflictError(Exception):
    """乐观锁冲突：保存时数据库版本已与快照不一致"""


class NotFoundError(Exception):
    """记录不存在"""


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def fmt(v):
    """四种空统一展示：None 与空串都显示为「—」（列表/查询界面统一口径）"""
    if v is None or v == "":
        return EMPTY
    return str(v)


def next_id(conn, table, pk_col, prefix, width):
    """系统生成编号：取当前最大序号 +1（如 S0001 → S0002），用户不可编辑"""
    row = conn.execute(
        f"SELECT MAX(CAST(SUBSTR({pk_col}, {len(prefix) + 1}) AS INTEGER)) AS m FROM {table}"
    ).fetchone()
    n = (row["m"] or 0) + 1
    return f"{prefix}{n:0{width}d}"


def dup_check(conn, table, col, val):
    """重复检测：返回 True 表示已存在"""
    return conn.execute(f"SELECT 1 FROM {table} WHERE {col} = ? LIMIT 1", (val,)).fetchone() is not None


def fetch_row(conn, table, pk_col, pk):
    return conn.execute(f"SELECT * FROM {table} WHERE {pk_col} = ?", (pk,)).fetchone()


def optimistic_update(conn, table, pk_col, pk, version, updates):
    """乐观锁保存：仅当数据库版本仍与快照一致时更新，否则抛 ConflictError。
    流程：加载记录时记快照版本 → 保存前用 WHERE version=? 比对 → 不一致则拦截并提示后保存者。
    空字符串一律按 NULL 入库（对应「留空即清空」的设计）。"""
    clean = {k: (None if v == "" else v) for k, v in updates.items()}
    now = datetime.now().isoformat(timespec="seconds")
    sets = ", ".join(f"{k} = ?" for k in clean)
    sql = (f"UPDATE {table} SET {sets}, version = version + 1, updated_at = ? "
           f"WHERE {pk_col} = ? AND version = ?")
    cur = conn.execute(sql, list(clean.values()) + [now, pk, version])
    conn.commit()
    if cur.rowcount == 0:
        exists = conn.execute(f"SELECT 1 FROM {table} WHERE {pk_col} = ?", (pk,)).fetchone()
        if exists:
            raise ConflictError("保存失败：该记录已被其他会话修改，请加载最新数据后重新编辑。")
        raise NotFoundError("保存失败：记录不存在。")
    return version + 1


def batch_update_years(conn, contract_id, payment_terms):
    """事务演示：将该合约全部年度的账期条款批量更新，返回旧值备份（供整体回滚）。"""
    rows = conn.execute(
        "SELECT contract_year_id, payment_terms FROM contract_years WHERE contract_id = ?",
        (contract_id,)).fetchall()
    backup = {r["contract_year_id"]: r["payment_terms"] for r in rows}
    try:
        conn.execute("BEGIN")
        now = datetime.now().isoformat(timespec="seconds")
        conn.execute(
            "UPDATE contract_years SET payment_terms = ?, version = version + 1, updated_at = ? "
            "WHERE contract_id = ?", (payment_terms, now, contract_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return backup


def rollback_batch(conn, backup):
    """事务演示：按备份整体恢复批量修改（失败则整体回滚，不留中间状态）。"""
    try:
        conn.execute("BEGIN")
        now = datetime.now().isoformat(timespec="seconds")
        for cid, old in backup.items():
            conn.execute(
                "UPDATE contract_years SET payment_terms = ?, version = version + 1, updated_at = ? "
                "WHERE contract_year_id = ?", (old, now, cid))
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def delete_cascade(conn, level, pk):
    """级联删除（单事务，任一步失败整体回滚）。level: 供应商/供货合约/合约年度"""
    try:
        conn.execute("BEGIN")
        if level == "供应商":
            for c in conn.execute("SELECT contract_id FROM contracts WHERE supplier_id = ?", (pk,)):
                _delete_contract(conn, c["contract_id"])
            conn.execute("DELETE FROM suppliers WHERE supplier_id = ?", (pk,))
        elif level == "供货合约":
            _delete_contract(conn, pk)
        else:  # 合约年度
            conn.execute("DELETE FROM split_details_pr WHERE contract_year_id = ?", (pk,))
            conn.execute("DELETE FROM split_details_xol WHERE contract_year_id = ?", (pk,))
            conn.execute("DELETE FROM contract_years WHERE contract_year_id = ?", (pk,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _delete_contract(conn, contract_id):
    for y in conn.execute(
            "SELECT contract_year_id FROM contract_years WHERE contract_id = ?", (contract_id,)):
        conn.execute("DELETE FROM split_details_pr WHERE contract_year_id = ?", (y["contract_year_id"],))
        conn.execute("DELETE FROM split_details_xol WHERE contract_year_id = ?", (y["contract_year_id"],))
        conn.execute("DELETE FROM contract_years WHERE contract_year_id = ?", (y["contract_year_id"],))
    conn.execute("DELETE FROM contracts WHERE contract_id = ?", (contract_id,))


def impact_preview(conn, level, pk):
    """删除前的影响预览：统计将被级联删除的记录数。"""
    lines = []
    if level == "供应商":
        lines.append(f"供应商记录 {pk}（1 条）")
        nc = conn.execute("SELECT COUNT(*) c FROM contracts WHERE supplier_id = ?", (pk,)).fetchone()["c"]
        ny = conn.execute(
            "SELECT COUNT(*) c FROM contract_years WHERE contract_id IN "
            "(SELECT contract_id FROM contracts WHERE supplier_id = ?)", (pk,)).fetchone()["c"]
        npr = conn.execute(
            "SELECT COUNT(*) c FROM split_details_pr WHERE contract_year_id IN "
            "(SELECT contract_year_id FROM contract_years WHERE contract_id IN "
            "(SELECT contract_id FROM contracts WHERE supplier_id = ?))", (pk,)).fetchone()["c"]
        nxol = conn.execute(
            "SELECT COUNT(*) c FROM split_details_xol WHERE contract_year_id IN "
            "(SELECT contract_year_id FROM contract_years WHERE contract_id IN "
            "(SELECT contract_id FROM contracts WHERE supplier_id = ?))", (pk,)).fetchone()["c"]
        lines += [f"关联供货合约 {nc} 条", f"合约年度 {ny} 条",
                  f"基础价格条款 {npr} 条", f"阶梯返利条款 {nxol} 条"]
    elif level == "供货合约":
        lines.append(f"供货合约 {pk}（1 条）")
        ny = conn.execute("SELECT COUNT(*) c FROM contract_years WHERE contract_id = ?", (pk,)).fetchone()["c"]
        npr = conn.execute(
            "SELECT COUNT(*) c FROM split_details_pr WHERE contract_year_id IN "
            "(SELECT contract_year_id FROM contract_years WHERE contract_id = ?)", (pk,)).fetchone()["c"]
        nxol = conn.execute(
            "SELECT COUNT(*) c FROM split_details_xol WHERE contract_year_id IN "
            "(SELECT contract_year_id FROM contract_years WHERE contract_id = ?)", (pk,)).fetchone()["c"]
        lines += [f"合约年度 {ny} 条", f"基础价格条款 {npr} 条", f"阶梯返利条款 {nxol} 条"]
    else:  # 合约年度
        lines.append(f"合约年度 {pk}（1 条）")
        npr = conn.execute("SELECT COUNT(*) c FROM split_details_pr WHERE contract_year_id = ?", (pk,)).fetchone()["c"]
        nxol = conn.execute("SELECT COUNT(*) c FROM split_details_xol WHERE contract_year_id = ?", (pk,)).fetchone()["c"]
        lines += [f"基础价格条款 {npr} 条", f"阶梯返利条款 {nxol} 条"]
    return lines


# ---------- 查询 ----------

def list_suppliers(conn, region=None, category=None, status=None, kw=None):
    sql, args = "SELECT * FROM suppliers WHERE 1=1", []
    if region:
        sql += " AND region = ?"; args.append(region)
    if category:
        sql += " AND category = ?"; args.append(category)
    if status:
        sql += " AND status = ?"; args.append(status)
    if kw:
        sql += " AND supplier_name LIKE ?"; args.append(f"%{kw}%")
    return conn.execute(sql + " ORDER BY supplier_id", args).fetchall()


def list_contracts(conn, supplier_id=None, status=None, kw=None):
    sql = ("SELECT c.*, s.supplier_name FROM contracts c "
           "JOIN suppliers s ON s.supplier_id = c.supplier_id WHERE 1=1")
    args = []
    if supplier_id:
        sql += " AND c.supplier_id = ?"; args.append(supplier_id)
    if status:
        sql += " AND c.status = ?"; args.append(status)
    if kw:
        sql += " AND (c.contract_no LIKE ? OR c.contract_name LIKE ?)"
        args += [f"%{kw}%", f"%{kw}%"]
    return conn.execute(sql + " ORDER BY c.contract_id", args).fetchall()


def list_years(conn, contract_id):
    return conn.execute(
        "SELECT * FROM contract_years WHERE contract_id = ? ORDER BY procurement_year, contract_year_id",
        (contract_id,)).fetchall()


def list_pr(conn, year_id):
    return conn.execute(
        "SELECT * FROM split_details_pr WHERE contract_year_id = ? ORDER BY pr_detail_id",
        (year_id,)).fetchall()


def list_xol(conn, year_id):
    return conn.execute(
        "SELECT * FROM split_details_xol WHERE contract_year_id = ? ORDER BY xol_detail_id",
        (year_id,)).fetchall()


def list_all_years(conn):
    """全部合约年度（带合约信息，用于新建条款时的选择列表）"""
    return conn.execute(
        "SELECT y.*, c.contract_no, c.contract_name FROM contract_years y "
        "JOIN contracts c ON c.contract_id = y.contract_id "
        "ORDER BY y.contract_year_id").fetchall()


# 编辑/删除页的层级列表（带关联展示字段）
LEVEL_QUERY = {
    "供应商": ("suppliers", "supplier_id",
               "SELECT supplier_id AS id, supplier_name AS name, status, contact_person, version "
               "FROM suppliers ORDER BY supplier_id"),
    "供货合约": ("contracts", "contract_id",
                "SELECT c.contract_id AS id, c.contract_no, c.contract_name AS name, "
                "s.supplier_name, c.status, c.version "
                "FROM contracts c JOIN suppliers s ON s.supplier_id = c.supplier_id "
                "ORDER BY c.contract_id"),
    "合约年度": ("contract_years", "contract_year_id",
                "SELECT y.contract_year_id AS id, c.contract_no, y.procurement_year, "
                "y.is_supplementary, y.payment_terms, y.version "
                "FROM contract_years y JOIN contracts c ON c.contract_id = y.contract_id "
                "ORDER BY y.contract_year_id"),
    "基础价格条款": ("split_details_pr", "pr_detail_id",
                    "SELECT p.pr_detail_id AS id, c.contract_no, p.sku_category, "
                    "p.base_discount_rate, p.version "
                    "FROM split_details_pr p JOIN contract_years y ON y.contract_year_id = p.contract_year_id "
                    "JOIN contracts c ON c.contract_id = y.contract_id ORDER BY p.pr_detail_id"),
    "阶梯返利条款": ("split_details_xol", "xol_detail_id",
                    "SELECT x.xol_detail_id AS id, c.contract_no, x.sku_category, "
                    "x.volume_threshold, x.version "
                    "FROM split_details_xol x JOIN contract_years y ON y.contract_year_id = x.contract_year_id "
                    "JOIN contracts c ON c.contract_id = y.contract_id ORDER BY x.xol_detail_id"),
}


def list_level(conn, level):
    return conn.execute(LEVEL_QUERY[level][2]).fetchall()


def level_table(level):
    return LEVEL_QUERY[level][0], LEVEL_QUERY[level][1]


# ---------- 总览统计 ----------

def stats(conn):
    out = {}
    for key, table in [("suppliers", "suppliers"), ("contracts", "contracts"),
                       ("years", "contract_years"), ("pr", "split_details_pr"),
                       ("xol", "split_details_xol")]:
        out[key] = conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]
    return out


def group_counts(conn, table, col):
    rows = conn.execute(f"SELECT {col} AS g, COUNT(*) AS c FROM {table} GROUP BY {col}").fetchall()
    return {r["g"]: r["c"] for r in rows}
