# 📦 供货合约管理台 · Supplier Contract Console

面向供应链采购团队的合约数据维护工具：覆盖供应商 → 供货合约 → 合约年度 → 条款明细四层数据的查询、编辑、新建、删除全流程，重点演示乐观锁并发防护、事务回滚、级联删除、重复检测等产品机制。

> **设计来源**：业务团队维护合同数据高度依赖 SQL 直改数据库，人工操作效率低、误改风险高，于是设计数据维护工具。本项目将该需求重建到供应链场景，代码与数据均从零构建。
>
> 🛡️ 合规声明：演示数据由脚本随机生成（固定随机种子），100% 虚构，不含任何真实数据。

🔗 **在线演示**：https://supplier-contract-console-bezpfmbjpmkxkux98u4xpx.streamlit.app/

## 🧭 版本演进

| 版本 | 内容 | 入口文件 | 在线演示 |
|---|---|---|---|
| v1 | 数据维护工具：查询/编辑/新建/删除 + 乐观锁、事务回滚、级联删除等机制（`release/v1` 分支冻结） | `app.py` | [v1 演示](https://supplier-contract-console-bezpfmbjpmkxkux98u4xpx.streamlit.app/) |
| v2 | AI Agent 探索版：自然语言查询 + 分析 + 图表（只读，写操作保留在 v1 人工执行）（`release/v2` 分支冻结） | `agent_app.py` | [v2 演示](https://supplier-contract-console-v2-offer4mian8fanglai.streamlit.app/) |
| v3 | 报告导出版：v2 问答能力 + 一键生成「供应商月度概况报告」（含供应商引入转化漏斗）/ 导出任意一轮问答（HTML 单文件，浏览器打印 PDF） | `report_app.py` | [v3 演示](https://supplier-contract-console-v3-offer4mian8fanglai.streamlit.app/) |

## ✨ 核心亮点

| 机制 | 一句话说明 | 演示入口 |
|---|---|---|
| **乐观锁并发防护** | 进入编辑时记录快照版本，保存前比对数据库版本，不一致则拦截后保存者 | 编辑页「⚡ 模拟另一用户修改」 |
| **事务回滚** | 批量修改单事务提交，可一键按备份整体恢复 | 编辑页「批量修改 + 事务回滚」 |
| **级联删除** | 删除前展示影响预览（将连带删除 N 条记录），二次确认后单事务级联清理 | 删除页 |
| **重复检测** | 供应商名称、合约编号、同合约同年度协议类型均做查重拦截 | 新建页 |
| **四种空统一展示** | NULL / 空串 / 空白在界面上统一显示为「—」，避免业务误读 | 查询页（37 家供应商电话为空可看） |
| **级联下钻查询** | 供应商 → 合约 → 年度 → 条款四层点击下钻 + 多维筛选 + CSV 导出 | 查询页 |

## 🧭 数据模型

```
suppliers 供应商（80 家虚构示例）
  ├─ supplier_events 供应商状态流转事件（234 条：建档 → 转考察 → 转合作/终止，月报转化漏斗的数据源）
  └─ contracts 供货合约（1,200 条）
       └─ contract_years 合约年度（采购年度 + 补充协议标记）
            ├─ split_details_pr  基础价格条款（折扣率/结算周期）
            └─ split_details_xol 阶梯返利条款（采购量超额返点）
```

6 张表均带 `version`（乐观锁）与 `updated_at` 字段；编号（S0001、C0001…）由系统生成，用户不可编辑。

## 🚀 快速开始

```bash
pip install -r requirements.txt     # streamlit
python generate_fake_data.py        # 生成演示数据库 console.db（可重复生成）
streamlit run app.py                # 启动，浏览器自动打开
```

可选：`python test_smoke.py` 运行自动化冒烟测试（AppTest，不污染演示数据）。

v2/v3 本地运行：

```bash
streamlit run agent_app.py      # v2 · AI Agent 问答
streamlit run report_app.py     # v3 · 问答 + 报告导出
python test_agent.py            # v2 golden questions 冒烟测试
python test_report.py           # v3 报告生成冒烟测试
```

> 同一仓库可部署多个 Streamlit app：每个 app 对应一个分支 + 入口文件，互不影响（v1/v2/v3 三个版本各自独立链接）。

## 🛡 核心机制详解

**乐观锁（编辑页）**

```
用户 A 进入编辑 → 快照 version=3
用户 B 保存 → version 3→4
用户 A 点击保存 → WHERE version=3 匹配 0 行 → 拦截
               → 提示「该记录已被其他会话修改」→ 重新加载最新数据
```

应用内点击「⚡ 模拟另一用户修改」即可演示完整冲突链路。

**事务回滚（编辑页）**：某合约 2 个年度批量改账期 → 单事务提交 → 「↩ 回滚」按保存的旧值备份整体恢复，不留中间状态。

**级联删除（删除页）**：删除供应商 → 自动级联其合约/年度/条款，执行前强制展示影响预览并勾选确认，全部操作在单事务内，失败整体回滚。

## 🎬 面试演示脚本（约 3 分钟）

1. **总览**：5 项核心指标 + 区域/品类/状态分布看板
2. **查询**：区域筛选 → 点击供应商下钻 → 合约 → 年度 → 条款；指出「—」四种空展示；导出 CSV
3. **编辑**：改一条记录 → 点「模拟另一用户修改」→ 再保存 → 看乐观锁拦截；再演示批量修改 + 回滚
4. **新建**：故意输入重复的合约编号 → 看查重拦截
5. **删除**：选一个供应商 → 看影响预览 → 勾选确认 → 级联删除

## 🤖 AI 结对开发日志

本项目由作者与 AI 结对开发完成，AI 承担代码生成、测试用例与审查，作者负责产品设计、机制决策与验收——完整覆盖「用 AI 工具完成原型设计、开发、验证」的闭环。

- **2026-09-05** 产品设计：梳理业务需求，完成供应链领域建模（供应商 → 供货合约 → 合约年度 → 基础价格条款/阶梯返利条款），确定 5 表三层模型
- **2026-09-06** M0-M5 开发：
  - 假数据生成脚本踩坑：合约编号随机生成触发 `UNIQUE` 约束冲突 → 改为由唯一主键派生编号，并补上「重跑先清旧库」的可重复生成设计
  - 编写 AppTest 冒烟测试时发现：新建成功后 `st.rerun()` 会清掉成功提示，导致「未成功」误报 → 改为直接查库断言 + 按名称清理测试数据
  - 随 Streamlit 升级迁移 `use_container_width` → `width="stretch"` 弃用 API
- 日常开发模式：提出需求 → AI 出方案/代码 → 人工 review 关键机制（乐观锁、事务边界）→ 自动化冒烟测试 + 机制级验证脚本

## 📦 部署到 Streamlit Cloud（免费）

1. 将本仓库推送到 GitHub（公开仓库）：[github.com/HaitangCui/supplier-contract-console](https://github.com/HaitangCui/supplier-contract-console)
2. 打开 [streamlit.io/cloud](https://streamlit.io/cloud)，用 GitHub 账号登录
3. 「New app」→ 搜索选择本仓库，Branch 填 `main`，Main file path 填 `app.py` → Deploy
4. 部署完成后进入 App Settings → Sharing，**设为 Public**（否则他人访问会看到登录墙）
5. 获得公开演示链接

## 📁 目录结构

```
supplier-contract-console/
├── app.py                  # v1 Streamlit 应用（总览/查询/编辑/新建/删除 5 模块）
├── db.py                   # 数据访问层（乐观锁/事务/级联/查询）
├── schema.sql              # 6 表 schema（含 version 乐观锁字段 + 供应商状态流转表）
├── generate_fake_data.py   # 虚构数据生成脚本（随机种子固定）
├── agent.py                # v2/v3 Agent 核心（SQL 只读四层防护 + 画图工具 + 只读查询函数）
├── agent_app.py            # v2 入口（AI 问答：聊天 + 图表 + 限流 + 自检）
├── report_gen.py           # v3 报告生成（模板月报 + 问答导出 → 单文件 HTML）
├── report_app.py           # v3 入口（v2 问答 + 一键报告导出）
├── test_smoke.py           # v1 AppTest 冒烟测试
├── test_agent.py           # v2 golden questions 冒烟测试
├── test_report.py          # v3 报告生成冒烟测试（数字与直查数据库交叉验证）
├── console.db              # 演示数据库（脚本生成，随仓库分发）
└── requirements.txt
```
