---
name: chart-renderer
description: "使用 `chart:render` 围栏输出 ECharts 交互式图表。当数据趋势、分布、对比或组成关系用图形比表格或文字更直观时使用。支持柱状图、折线图、饼图、散点图和雷达图。"
---

# Chart Renderer

将数据分析结论用普通 Markdown 阐述后，在需要图形化的位置插入一个
`chart:render` 围栏。围栏内容为合法的 ECharts option JSON，前端自动渲染为交互式图表。

## 输出格式

1. 先用普通 Markdown 写结论和必要解释。
2. 顶格写开始围栏 ```` ```chart:render ````。围栏最多只能有 3 个前导空格。
3. 在围栏内写一个完整的 ECharts option JSON 对象。
4. 顶格写结束围栏 ```` ``` ````。
5. 在围栏后用普通 Markdown 补充解读、数据来源和注意事项。

## JSON 规范

- 必须是合法 JSON：无注释、无尾逗号、键名用双引号。
- 顶层是一个 `{}` 对象，即 ECharts 的 option。
- 前端自动注入 Yuxi 调色盘颜色；如果不需要自定义配色，不要写 `color` 字段。
- 默认图表高度 360px，容器宽度 100%。

## 支持的图表类型

| 类型 | series.type | 必要字段 |
|---|---|---|
| 柱状图 | `bar` | `xAxis` + `series[].data` |
| 折线图 | `line` | `xAxis` + `series[].data` |
| 饼图 | `pie` | `series[].data`（`{name, value}` 数组） |
| 散点图 | `scatter` | `series[].data`（`[x, y]` 数组） |
| 雷达图 | `radar` | `radar.indicator` + `series[].data` |

## 最小示例

### 柱状图

```chart:render
{
  "title": { "text": "季度营收" },
  "tooltip": { "trigger": "axis" },
  "xAxis": { "type": "category", "data": ["Q1", "Q2", "Q3", "Q4"] },
  "yAxis": { "type": "value" },
  "series": [
    { "type": "bar", "data": [120, 200, 150, 180] }
  ]
}
```

### 饼图

```chart:render
{
  "tooltip": { "trigger": "item" },
  "series": [
    {
      "type": "pie",
      "radius": ["40%", "70%"],
      "data": [
        { "name": "产品A", "value": 1048 },
        { "name": "产品B", "value": 735 },
        { "name": "产品C", "value": 580 }
      ]
    }
  ]
}
```

### 多系列折线图

```chart:render
{
  "tooltip": { "trigger": "axis" },
  "legend": { "data": ["邮件", "联盟", "视频"] },
  "xAxis": { "type": "category", "data": ["周一", "周二", "周三", "周四", "周五"] },
  "yAxis": { "type": "value" },
  "series": [
    { "name": "邮件", "type": "line", "data": [120, 132, 101, 134, 90] },
    { "name": "联盟", "type": "line", "data": [220, 182, 191, 234, 290] },
    { "name": "视频", "type": "line", "data": [150, 232, 201, 154, 190] }
  ]
}
```

## 内容边界

- 数据点不超过 30 个；超过时汇总为趋势、区间或 Top N。
- 系列数不超过 5 个；超过时合并为「其他」或只展示关键系列。
- 标签文字简短（≤10 字符），长名称用 `tooltip` 展示完整信息。
- 不使用动画配置（`animation`）、不绑定事件、不写 `toolbox`——前端已提供默认交互。
- 不使用 `dataset`，直接在 `series[].data` 内联数据。

## 何时使用

- 数值趋势、对比、占比或分布用图形明显更直观时。
- 用户明确要求「画图」「图表」「可视化」时。
- 数据分析结果需要图形辅助理解时。

## 何时不使用

- 1–3 个数值对比：用表格或 Markdown 即可。
- 非数值内容（流程、架构、时间线）：用 `html:preview` 或 Mermaid。
- 用户要复制图表代码：直接输出 JSON 代码块，不用 `chart:render`。

## 失败处理

如果数据无法在以上边界内有效展示，改用普通 Markdown 表格，并说明原因。不要输出残缺 JSON 或无效围栏。
