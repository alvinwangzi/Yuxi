---
name: data-analysis
description: "分析用户上传的 Excel (.xlsx/.xls) 或 CSV 文件。支持查看文件结构、SQL 查询、统计摘要和结果导出。基于 DuckDB 内存分析引擎，无需外部数据库。"
---

# 数据分析技能

根据用户指令，通过终端脚本分析 Excel 或 CSV 文件，支持结构查看、SQL 查询、统计摘要和结果导出。

## 操作流程

1. 理解用户的分析需求，明确要分析的文件和目标
2. 通过 terminal 进入技能目录：`cd /home/gem/skills/data-analysis`
3. 用 `uv run scripts/analyze.py --files <文件路径> --action inspect` 查看文件结构（sheet 名、列名、类型、行数、样例数据）
4. 根据文件结构和用户需求，用 `uv run scripts/analyze.py --files <文件路径> --action query --sql "SQL语句"` 执行查询
5. 必要时用 `uv run scripts/analyze.py --files <文件路径> --action summary --table <表名>` 获取统计摘要
6. 如需导出结果，追加 `--output-file outputs/result.csv`（支持 .csv / .json / .md）
7. 将导出文件通过 `present_artifacts` 展示给用户

## 参数说明

| 参数 | 必填 | 说明 |
|------|------|------|
| `--files` | 是 | 空格分隔的文件路径，支持 .xlsx / .xls / .csv，多文件可同时加载 |
| `--action` | 是 | `inspect`（查看结构）、`query`（SQL 查询）、`summary`（统计摘要） |
| `--sql` | query 时必填 | SQL 查询语句，支持跨文件 JOIN、窗口函数、CTE |
| `--table` | summary 时必填 | 要统计的表名（原始 sheet 名或文件名） |
| `--output-file` | 否 | 导出结果的文件路径，扩展名决定格式：.csv / .json / .md |

> 不要读取 analyze.py 源码，只通过 CLI 参数调用。

## 表名规则

- Excel 文件：每个 sheet 成为一张表，表名为 sheet 名（特殊字符替换为下划线，数字开头加 `t_` 前缀）
- CSV 文件：表名为文件名去掉扩展名（同样净化处理）
- 多文件：所有表在同一查询上下文中，支持跨文件 JOIN
- 重名自动编号（如 `Sheet1`、`Sheet1_1`）

## 分析示例

### 基础探索

```bash
# 查看文件结构
uv run scripts/analyze.py --files uploads/sales.xlsx --action inspect

# 统计摘要
uv run scripts/analyze.py --files uploads/sales.xlsx --action summary --table Orders
```

### SQL 查询

```bash
# 分组聚合
uv run scripts/analyze.py --files uploads/sales.xlsx --action query \
  --sql "SELECT category, SUM(revenue) as total FROM Orders GROUP BY category ORDER BY total DESC LIMIT 10"

# 导出结果
uv run scripts/analyze.py --files uploads/sales.xlsx --action query \
  --sql "SELECT * FROM Orders WHERE amount > 1000" \
  --output-file outputs/filtered.csv
```

### 跨文件 JOIN

```bash
uv run scripts/analyze.py --files uploads/orders.csv uploads/customers.xlsx --action query \
  --sql "SELECT c.region, AVG(o.amount) as avg_order FROM orders o JOIN customers c ON o.customer_id = c.id GROUP BY c.region ORDER BY avg_order DESC"
```

## 关键约束

- 所有数据操作通过 DuckDB SQL，不直接操作原始文件
- 不要读取 analyze.py 源码，只通过 CLI 参数调用
- 查询结果中的大数值使用千分位逗号格式化
- 导出文件建议放在当前 Project Workdir 的 `outputs/` 下，并调用 `present_artifacts` 展示
- DuckDB 支持完整 SQL 语法，包括窗口函数、CTE、子查询和高级聚合

## 允许的工具

- terminal：执行 `scripts/analyze.py`
- present_artifacts：展示导出的结果文件
- 网络检索工具：必要时补充背景信息
