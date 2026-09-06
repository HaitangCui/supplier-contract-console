# -*- coding: utf-8 -*-
"""Supplier Contract Console · 假数据生成脚本
生成 100% 虚构的供应链合约数据（供应商 80 家 / 合约 1,200 条 / 年度 2,600+ / 明细若干）。
random.seed 固定，可重复生成。不含任何真实企业数据。
"""
import random
import sqlite3
import os
from datetime import date, timedelta

random.seed(2026)
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "console.db")
if os.path.exists(DB):
    os.remove(DB)  # 重跑脚本时先清掉旧库，保证可重复生成

REGIONS = ["华东", "华北", "华南", "华中", "西南", "西北", "东北"]
REGION_CITY = {
    "华东": ["杭州", "苏州", "宁波", "无锡", "南京"],
    "华北": ["天津", "石家庄", "唐山", "保定", "济南"],
    "华南": ["广州", "佛山", "东莞", "深圳", "福州"],
    "华中": ["武汉", "长沙", "郑州", "合肥", "南昌"],
    "西南": ["成都", "重庆", "昆明", "贵阳", "绵阳"],
    "西北": ["西安", "兰州", "银川", "西宁", "乌鲁木齐"],
    "东北": ["沈阳", "大连", "长春", "哈尔滨", "吉林"],
}
CATEGORIES = ["生鲜果蔬", "肉禽冻品", "粮油调味", "酒水饮料", "包装耗材", "冷链物流"]
SKU_CATEGORIES = ["叶菜类", "根茎类", "猪肉", "禽肉", "海鲜冻品", "食用油", "调味品", "啤酒", "饮料", "纸箱", "保温箱", "冰袋", "干线运输", "城市配送"]
ADJ = ["鲜美", "优选", "丰源", "绿洲", "恒达", "瑞丰", "盛泰", "宏远", "金穗", "润泽", "康泰", "天润"]
STYLE = ["供应链", "食品", "农产品", "商贸", "冷链物流", "实业", "贸易", "配送"]

PAYMENT_TERMS = ["月结30天", "月结45天", "月结60天", "现结", "预付30%+月结"]
DELIVERY_TERMS = ["次日达", "隔日达", "每周2次配送", "每周3次配送", "产地直发", None]
CONTRACT_TYPES = ["框架协议", "单次供货"]
CONTRACT_STATUS = ["生效中", "生效中", "生效中", "已到期", "草稿", "已终止"]

def d(days_offset):
    return (date(2026, 9, 5) + timedelta(days=days_offset)).isoformat()

conn = sqlite3.connect(DB)
cur = conn.cursor()

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql"), encoding="utf-8") as f:
    cur.executescript(f.read())

# ---- 供应商 80 家 ----
suppliers = []
for i in range(1, 81):
    sid = f"S{i:04d}"
    region = random.choice(REGIONS)
    city = random.choice(REGION_CITY[region])
    name = city + random.choice(ADJ) + random.choice(CATEGORIES) + random.choice(STYLE) + "有限公司"
    status = random.choices(["合作中", "合作中", "合作中", "考察期", "已终止"], weights=[7, 7, 7, 2, 1])[0]
    contact = random.choice([None, "张经理", "李经理", "王经理", "刘经理", "陈经理"])
    phone = random.choice([None, "13" + str(random.randint(100000000, 999999999))])
    suppliers.append((sid, name, region, random.choice(CATEGORIES), contact, phone, status, d(-random.randint(100, 1200))))

cur.executemany(
    "INSERT INTO suppliers (supplier_id, supplier_name, region, category, "
    "contact_person, contact_phone, status, created_at) VALUES (?,?,?,?,?,?,?,?)", suppliers)

# ---- 合约 1,200 条 ----
contracts = []
contract_years = []
pr_details = []
xol_details = []
cid = year_id = pr_id = xol_id = 0

for c in range(1, 1201):
    cid += 1
    contract_id = f"C{cid:04d}"
    supplier = random.choice(suppliers)
    ctype = random.choice(CONTRACT_TYPES)
    status = random.choice(CONTRACT_STATUS)
    signed = d(-random.randint(60, 900))
    valid_from = d(-random.randint(30, 850))
    valid_to = d(random.randint(60, 600))
    note = random.choice([None, None, None, "含售后条款", "含包材回收条款"])
    contracts.append((contract_id, supplier[0],
                      f"CT{random.randint(2023, 2026)}{cid:05d}",  # cid 唯一 → 编号唯一
                      f"{random.choice(SKU_CATEGORIES)}年度供货", ctype, status, signed, valid_from, valid_to, note))

    # 每份合约 1-3 个合约年度
    for y in range(random.randint(1, 3)):
        year_id += 1
        cyid = f"CY{year_id:05d}"
        pyear = random.randint(2024, 2027)
        is_supp = 1 if random.random() < 0.10 else 0  # 10% 为补充协议
        pt = random.choice(PAYMENT_TERMS)
        dt = random.choice(DELIVERY_TERMS)
        ynote = random.choice([None, None, None, "旺季价格另议", "含运输补贴"])
        contract_years.append((cyid, contract_id, pyear, is_supp, pt, dt, ynote))

        # 1-3 条基础价格条款
        for _ in range(random.randint(1, 3)):
            pr_id += 1
            pr_details.append((f"PR{pr_id:05d}", cyid, random.choice(SKU_CATEGORIES),
                               round(random.choice([0.85, 0.88, 0.90, 0.92, 0.95, 0.97]), 2),
                               random.choice(["月结", "季结", "半年结"]),
                               random.choice([None, "含税", "不含税"])))

        # 0-2 条阶梯返利条款
        for _ in range(random.randint(0, 2)):
            xol_id += 1
            xol_details.append((f"XO{xol_id:05d}", cyid, random.choice(SKU_CATEGORIES),
                                random.choice([5000, 10000, 20000, 50000, 100000]),
                                round(random.uniform(0.02, 0.08), 3),
                                random.choice([None, 50000, 100000, 200000]),
                                random.choice([None, "超额部分按比例返点", "年底统一结算"])))

cur.executemany(
    "INSERT INTO contracts (contract_id, supplier_id, contract_no, contract_name, "
    "contract_type, status, signed_date, valid_from, valid_to, note) VALUES (?,?,?,?,?,?,?,?,?,?)",
    contracts)
cur.executemany(
    "INSERT INTO contract_years (contract_year_id, contract_id, procurement_year, "
    "is_supplementary, payment_terms, delivery_terms, note) VALUES (?,?,?,?,?,?,?)", contract_years)
cur.executemany(
    "INSERT INTO split_details_pr (pr_detail_id, contract_year_id, sku_category, "
    "base_discount_rate, settlement_cycle, note) VALUES (?,?,?,?,?,?)", pr_details)
cur.executemany(
    "INSERT INTO split_details_xol (xol_detail_id, contract_year_id, sku_category, "
    "volume_threshold, rebate_rate, rebate_cap, note) VALUES (?,?,?,?,?,?,?)", xol_details)

conn.commit()

# 汇总报告（输出到文件，避免控制台乱码）
report = []
for t in ["suppliers", "contracts", "contract_years", "split_details_pr", "split_details_xol"]:
    cur.execute(f"SELECT COUNT(*) FROM {t}")
    report.append(f"{t}: {cur.fetchone()[0]}")
cur.execute("SELECT COUNT(*) FROM suppliers WHERE contact_phone IS NULL")
report.append(f"suppliers with NULL phone (演示四种空): {cur.fetchone()[0]}")
cur.execute("SELECT COUNT(*) FROM contract_years WHERE is_supplementary=1")
report.append(f"补充协议年度: {cur.fetchone()[0]}")
report.append(f"db size: {os.path.getsize(DB)/1024:.0f} KB")

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_report.txt")
with open(out, "w", encoding="utf-8") as f:
    f.write("\n".join(report))
conn.close()
print("done")
