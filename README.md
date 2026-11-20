# Olist E-Commerce Operations & Delivery Optimization Analysis

![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![Pandas](https://img.shields.io/badge/Pandas-2.0.3-150458)
![MySQL](https://img.shields.io/badge/MySQL-8.0-4479A1)
![Power BI](https://img.shields.io/badge/PowerBI-Desktop-F2C811)
![License](https://img.shields.io/badge/License-MIT-green)

这是一个基于真实的巴西电商数据集（Olist）构建的**端到端数据分析项目**。技术主线为 **Python → Parquet → MySQL → Power BI**。

项目致力于回答四个核心业务问题：
* 经营变化的核心驱动因素是什么？
* 哪些履约/物流问题与差评高度相关？
* 应当优先干预和跟进哪些卖家？
* 不同客户在相同的观察窗口内的复购表现如何？

---

## 🛠️ 技术栈

* **数据清洗与处理**：Python (Pandas, PyArrow, NumPy)
* **数据存储与分析**：MySQL, Parquet
* **数据可视化**：Power BI
* **文档与 Notebook**：Jupyter Notebook, Markdown

---

## 📂 项目结构

```text
olist-operations-analytics/
├── archive/            # 原始 CSV 数据文件 (需自行从 Kaggle 下载)
├── docs/               # 项目路线图、指标口径与业务指导文档
├── notebooks/          # Jupyter 探索性分析笔记
├── src/                # 可重复执行的数据清洗与处理脚本
├── sql/                # 数据建表、加载核对与业务分析 SQL
├── reports/            # 数据盘点、清洗质量报告与业务分析报告
├── powerbi/            # Power BI 仪表板文件 (.pbix)
└── requirements.txt    # 核心依赖及版本说明
```

---

## 🚀 快速开始

### 1. 环境准备

本项目推荐使用 Python 3.8.20 及以上版本。

```bash
# 创建并激活虚拟环境
python -m venv .venv
.\.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # macOS/Linux

# 安装依赖（请根据实际执行的阶段选择对应的依赖文件）
pip install -r requirements.txt
# 如需运行 Notebook 或 MySQL 导入，请安装：
# pip install -r requirements-notebooks.txt
# pip install -r requirements-mysql.txt
```

### 2. 数据准备

请前往 [Kaggle Olist 数据集](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) 下载原始数据（共 9 张表），并将其解压至项目的 `archive/` 目录下。**请确保原始数据与代码仓库分开管理。**

### 3. 数据处理流水线

本项目的清洗流程分为多个阶段，每个阶段都会生成独立的数据集与质量核对报告（位于 `data/processed/` 与 `reports/`）：

```bash
# 阶段 1: 生成原始数据盘点报告
python src/01_profile_raw.py

# 阶段 2: 各业务模块清洗 (以订单为例)
# 默认运行六规则 v1，可加 --rules-version v2 生成八规则 v2
python src/02_clean_orders.py 

# 阶段 3: 导出为 Parquet 格式 (供 MySQL 导入和 Power BI 使用)
python src/10_export_parquet.py
```

*注：脚本 `02` 至 `09` 分别对应订单、明细、支付、评价、客户、商品、卖家、地理等 9 张表的清洗与关联。清洗过程中保留完整明细与核对逻辑，不擅自修正跨表差异，具体逻辑及字段字典请参考 `docs/` 目录。*

### 4. 数据库与 BI 分析

* 将 `data/processed/mysql_input_v1/` 中的 Parquet 数据导入 MySQL。
* 执行 `sql/` 目录下的查询脚本（包含 30+ 业务专题 SQL、窗口函数与 CTE 分析）。
* 通过 `python src/15_export_powerbi.py` 生成 BI 层分析数据。
* 在 Power BI Desktop 中完成可视化报表后，保存至 `powerbi/` 目录。

---

## 💡 业务分析路线图

项目从问题定义到最终报表，遵循以下结构化路径：

1. **原始数据认知**：识别九张表的主键/外键、空值分布与业务含义。
2. **数据清洗与标准化**：处理缺失值、类型转换、州代码映射与多表关联。
3. **核心指标构建**：定义 GMV、客单价、妥投时间、差评率等业务指标口径。
4. **MySQL 深度分析**：运用窗口函数、CTE 与多表 Join 计算复购率、卖家画像等。
5. **Power BI 可视化**：搭建成交额瀑布图、交付延迟异常象限图等交互式报表。
6. **业务洞察与总结**：输出针对性的运营优化建议（如优先跟进卖家清单）。

---

## 📊 分析产出

本项目按阶段交付以下成果，以保证结论的**可复现性**与**可追溯性**：

1. **清洗代码与质量报告**：记录数据输入输出、控制总额与关联核对逻辑。
2. **业务分析报告**：位于 `reports/`，包含数据盘点、交叉验证与专题分析结论。
3. **可视化仪表板**：涵盖经营增长（瀑布图）、履约优化、卖家管理、客户复购等 8 页 Power BI 报表。
4. **教学与复盘文档**：位于 `docs/`，包含 50+ 课时的完整分析路线、思路与操作记录，方便读者复现项目。

---

## 📄 开源协议 & 数据声明

* **代码协议**：本项目代码基于 [MIT License](LICENSE) 开源。
* **数据版权**：本项目使用的数据来自公开的 Olist 电商数据集，版权及使用规范请严格遵循 [Kaggle 官方说明](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)。在公开作品集展示时，请务必将原始数据、代码与可视化图表分开管理。
