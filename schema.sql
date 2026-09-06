-- Supplier Contract Console · 供货合约管理台
-- SQLite schema —— 5 张核心表，对应「供应商 → 供货合约 → 合约年度 → 分账/返利明细」三层关系模型
-- 每张表都带 version（乐观锁）与 updated_at（最后修改时间）

-- 1. 供应商
CREATE TABLE suppliers (
    supplier_id     TEXT PRIMARY KEY,           -- 如 S0001（系统生成，用户不可编辑）
    supplier_name   TEXT NOT NULL,              -- 供应商名称
    region          TEXT NOT NULL,              -- 所在区域：华东/华北/华南/华中/西南/西北/东北
    category        TEXT NOT NULL,              -- 供应品类：生鲜果蔬/肉禽冻品/粮油调味/酒水饮料/包装耗材/冷链物流
    contact_person  TEXT,                       -- 联系人（可空）
    contact_phone   TEXT,                       -- 联系电话（可空）
    status          TEXT NOT NULL DEFAULT '合作中',  -- 合作中/已终止/考察期
    created_at      TEXT NOT NULL,              -- 建档日期
    version         INTEGER NOT NULL DEFAULT 1, -- 乐观锁版本号
    updated_at      TEXT                        -- 最后修改时间
);

-- 2. 供货合约
CREATE TABLE contracts (
    contract_id     TEXT PRIMARY KEY,           -- 如 C0001
    supplier_id     TEXT NOT NULL REFERENCES suppliers(supplier_id),
    contract_no     TEXT NOT NULL UNIQUE,       -- 合约唯一编号（同一供应商+年度靠它区分补充协议）
    contract_name   TEXT NOT NULL,              -- 合约名称
    contract_type   TEXT NOT NULL,              -- 框架协议 / 单次供货
    status          TEXT NOT NULL DEFAULT '生效中',  -- 生效中/已到期/草稿/已终止
    signed_date     TEXT,                       -- 签订日期
    valid_from      TEXT NOT NULL,              -- 生效日期
    valid_to        TEXT NOT NULL,              -- 到期日期
    note            TEXT,                       -- 备注（可空，演示「四种空」统一展示）
    version         INTEGER NOT NULL DEFAULT 1,
    updated_at      TEXT
);

-- 3. 合约年度
CREATE TABLE contract_years (
    contract_year_id    TEXT PRIMARY KEY,       -- 如 CY00001
    contract_id         TEXT NOT NULL REFERENCES contracts(contract_id),
    procurement_year    INTEGER NOT NULL,       -- 采购年度
    is_supplementary    INTEGER NOT NULL DEFAULT 0,  -- 是否补充协议（同一合约同一年度可有多份）
    payment_terms       TEXT NOT NULL,          -- 账期条款：月结30天/月结45天/现结/预付
    delivery_terms      TEXT,                   -- 交付条款（可空）
    note                TEXT,
    version             INTEGER NOT NULL DEFAULT 1,
    updated_at          TEXT
);

-- 4. 基础价格条款明细
CREATE TABLE split_details_pr (
    pr_detail_id        TEXT PRIMARY KEY,       -- 如 PR00001
    contract_year_id    TEXT NOT NULL REFERENCES contract_years(contract_year_id),
    sku_category        TEXT NOT NULL,          -- 物料品类
    base_discount_rate  REAL NOT NULL,          -- 基础折扣率（如 0.92 = 92 折）
    settlement_cycle    TEXT NOT NULL,          -- 结算周期：月结/季结/半年结
    note                TEXT,
    version             INTEGER NOT NULL DEFAULT 1,
    updated_at          TEXT
);

-- 5. 阶梯返利条款明细（采购量超额返点）
CREATE TABLE split_details_xol (
    xol_detail_id       TEXT PRIMARY KEY,       -- 如 XO00001
    contract_year_id    TEXT NOT NULL REFERENCES contract_years(contract_year_id),
    sku_category        TEXT NOT NULL,          -- 物料品类
    volume_threshold    REAL NOT NULL,          -- 起返采购量（件）
    rebate_rate         REAL NOT NULL,          -- 超额部分返利比例（如 0.05 = 5%）
    rebate_cap          REAL,                   -- 返利封顶金额（元，可空=不封顶）
    note                TEXT,
    version             INTEGER NOT NULL DEFAULT 1,
    updated_at          TEXT
);

CREATE INDEX idx_contracts_supplier ON contracts(supplier_id);
CREATE INDEX idx_years_contract ON contract_years(contract_id);
CREATE INDEX idx_pr_year ON split_details_pr(contract_year_id);
CREATE INDEX idx_xol_year ON split_details_xol(contract_year_id);
