import assert from 'node:assert/strict'
import test from 'node:test'

import { renderChartBlocks } from '../../src/utils/chartRenderer.js'

test('chart:render fenced blocks render containers and preserve other content', () => {
  // 基本柱状图围栏被转换为容器 div
  {
    const input = 'before\n```chart:render\n{ "title": { "text": "test" } }\n```\nafter'
    const result = renderChartBlocks(input)
    assert.ok(result.includes('chart-render-container'))
    assert.ok(result.includes('chart-render-canvas'))
    assert.ok(result.includes('chart-render-spec'))
    assert.ok(!result.includes('```chart:render'))
    assert.ok(result.includes('before'))
    assert.ok(result.includes('after'))
  }

  // 波浪线围栏同样生效
  {
    const result = renderChartBlocks('~~~chart:render\n{ "xAxis": {} }\n~~~')
    assert.ok(result.includes('chart-render-container'))
    assert.ok(result.includes('chart-render-spec'))
  }

  // JSON 内容被 HTML 转义后存入 <pre>
  {
    const result = renderChartBlocks('```chart:render\n{ "a": "<b>" }\n```')
    assert.ok(result.includes('&lt;b&gt;'))
    assert.ok(!result.includes('chart-render-spec">\n{ "a": "<b>" }'))
  }

  // 未闭合围栏渲染为加载占位
  {
    const result = renderChartBlocks('before\n```chart:render\n{ "title": "incomplete"')
    assert.ok(result.includes('chart-render-container'))
    assert.ok(result.includes('图表加载中'))
    assert.ok(!result.includes('chart-render-spec'))
    assert.ok(result.includes('before'))
  }

  // 非 chart:render 的代码块保持不变
  {
    const result = renderChartBlocks('```python\nprint(1)\n```')
    assert.ok(result.includes('```python'))
    assert.ok(!result.includes('chart-render-container'))
  }

  // 多个图表围栏都能正确渲染
  {
    const input = '```chart:render\n{ "id": 1 }\n```\ntext\n```chart:render\n{ "id": 2 }\n```'
    const result = renderChartBlocks(input)
    const matches = result.match(/chart-render-container/g)
    assert.equal(matches ? matches.length : 0, 2)
    const specMatches = result.match(/chart-render-spec/g)
    assert.equal(specMatches ? specMatches.length : 0, 2)
    assert.ok(result.includes('text'))
  }

  // 空围栏不生成容器
  {
    const result = renderChartBlocks('```chart:render\n```')
    assert.ok(!result.includes('chart-render-container'))
  }

  // 纯文本不受影响
  {
    const result = renderChartBlocks('hello world\n\nsome text')
    assert.equal(result, 'hello world\n\nsome text')
  }

  // 围栏前后内容完整保留
  {
    const result = renderChartBlocks('some text before\n\n```chart:render\n{ "x": 1 }\n```')
    assert.ok(result.includes('chart-render-container'))
    assert.ok(result.includes('some text before'))
  }

  // 与 Markdown 标题和段落混合
  {
    const input = '# Title\n\n```chart:render\n{ "series": [] }\n```\n\nSome text\n\n# End'
    const result = renderChartBlocks(input)
    assert.ok(result.includes('chart-render-container'))
    assert.ok(result.includes('# Title'))
    assert.ok(result.includes('Some text'))
    assert.ok(result.includes('# End'))
  }

  // 多行 JSON 保持完整
  {
    const input = [
      '```chart:render',
      '{',
      '  "title": { "text": "Revenue" },',
      '  "xAxis": { "data": ["Q1", "Q2"] },',
      '  "series": [{ "type": "bar", "data": [100, 200] }]',
      '}',
      '```'
    ].join('\n')
    const result = renderChartBlocks(input)
    assert.ok(result.includes('chart-render-spec'))
    assert.ok(result.includes('Revenue'))
    assert.ok(result.includes('Q1'))
  }
})
