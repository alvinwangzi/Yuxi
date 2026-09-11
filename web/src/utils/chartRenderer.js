/**
 * ECharts 交互式图表渲染器
 *
 * 将 Markdown 中的 ```chart:render 围栏代码块转换为交互式 ECharts 图表。
 * 分两阶段工作：
 *   1. renderChartBlocks() — 在 Markdown→HTML 转换前，将围栏替换为容器 div
 *   2. enhanceChartContainers() — 在 DOM 更新后，初始化 ECharts 实例
 *
 * Agent 输出格式：
 *   ```chart:render
 *   { "title": { "text": "..." }, "xAxis": {...}, "series": [...] }
 *   ```
 */

const CHART_LANGUAGE = 'chart:render'
const CHART_CONTAINER_CLASS = 'chart-render-container'
const CHART_CANVAS_CLASS = 'chart-render-canvas'
const CHART_LOADING_CLASS = 'chart-render-loading'
const CHART_DEFAULT_HEIGHT = 360
const CHART_LOADING_HEIGHT = 120

const escapeForPre = (value) =>
  value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')

/**
 * 将单个已闭合的 chart:render 围栏转换为容器 HTML。
 * JSON 通过 hidden <pre> 的 textContent 存储，浏览器自动处理 HTML 转义。
 */
const renderChartBlock = (jsonContent) => {
  const trimmed = jsonContent.trim()
  if (!trimmed) return ''

  return [
    `<div class="${CHART_CONTAINER_CLASS}" style="--chart-height: ${CHART_DEFAULT_HEIGHT}px;">`,
    `<div class="${CHART_LOADING_CLASS}">图表加载中...</div>`,
    `<div class="${CHART_CANVAS_CLASS}" style="height: var(--chart-height);"></div>`,
    `<pre class="chart-render-spec">${escapeForPre(trimmed)}</pre>`,
    `</div>`
  ].join('')
}

/**
 * 渲染未闭合围栏的加载占位符
 */
const renderChartLoading = () =>
  `<div class="${CHART_CONTAINER_CLASS}" style="--chart-height: ${CHART_LOADING_HEIGHT}px;">` +
  `<div class="${CHART_LOADING_CLASS}">图表加载中...</div>` +
  `</div>`

/**
 * 将 Markdown 中的 ```chart:render 围栏代码块转换为图表容器。
 *
 * 遵循与 svgRenderer.js / htmlPreviewRenderer.js 相同的逐行扫描模式。
 * 未闭合的围栏渲染为加载占位块（流式安全）。
 *
 * @param {string} markdown - 原始 Markdown 字符串
 * @returns {string} 转换后的字符串
 */
export function renderChartBlocks(markdown) {
  const lines = String(markdown || '').split('\n')
  const output = []
  let i = 0

  while (i < lines.length) {
    const openMatch = lines[i].match(/^( {0,3})(`{3,}|~{3,})\s*(\S*)/)
    const language = openMatch?.[3]

    if (openMatch && language === CHART_LANGUAGE) {
      const indent = openMatch[1]
      const fenceChar = openMatch[2]
      const jsonLines = []
      i++

      let closed = false
      while (i < lines.length) {
        const closeMatch = lines[i].match(/^( {0,3})(`{3,}|~{3,})\s*$/)
        if (
          closeMatch &&
          closeMatch[1].length <= indent.length &&
          closeMatch[2][0] === fenceChar[0] &&
          closeMatch[2].length >= fenceChar.length
        ) {
          closed = true
          output.push(renderChartBlock(jsonLines.join('\n')))
          i++
          break
        }
        jsonLines.push(lines[i])
        i++
      }

      if (!closed) {
        // 未闭合 → 流式加载中
        output.push(renderChartLoading())
      }
    } else {
      output.push(lines[i])
      i++
    }
  }

  return output.join('\n')
}

// ─── 以下函数依赖浏览器 DOM 和 ECharts，仅在客户端调用 ───

let _echartsRegistered = false
let _echartsCore

/**
 * 首次调用时动态导入 echarts 并注册组件。
 * 避免在 Node.js 测试或 SSR 环境中触发浏览器依赖。
 */
const ensureEcharts = async () => {
  if (!_echartsRegistered) {
    const [
      { use },
      { BarChart, LineChart, PieChart, ScatterChart, RadarChart },
      {
        GridComponent,
        LegendComponent,
        TooltipComponent,
        TitleComponent,
        ToolboxComponent,
        DataZoomComponent,
        MarkLineComponent,
        MarkPointComponent
      },
      { LabelLayout, UniversalTransition },
      { CanvasRenderer },
      echartsCore
    ] = await Promise.all([
      import('echarts/core'),
      import('echarts/charts'),
      import('echarts/components'),
      import('echarts/features'),
      import('echarts/renderers'),
      import('echarts/core')
    ])

    use([
      BarChart,
      LineChart,
      PieChart,
      ScatterChart,
      RadarChart,
      GridComponent,
      LegendComponent,
      TooltipComponent,
      TitleComponent,
      ToolboxComponent,
      DataZoomComponent,
      MarkLineComponent,
      MarkPointComponent,
      LabelLayout,
      UniversalTransition,
      CanvasRenderer
    ])

    _echartsCore = echartsCore
    _echartsRegistered = true
  }
  return _echartsCore
}

/**
 * 在 DOM 中查找所有待初始化的 chart 容器，创建 ECharts 实例。
 *
 * @param {HTMLElement} root - MarkdownPreview 的根元素
 * @param {Map<string, object>} chartInstances - 追踪活跃的 ECharts 实例
 */
export async function enhanceChartContainers(root, chartInstances) {
  if (!root) return

  const containers = root.querySelectorAll(
    `.${CHART_CONTAINER_CLASS}:not([data-chart-init])`
  )
  if (containers.length === 0) return

  const echarts = await ensureEcharts()
  const { getColorPalette } = await import('./chartColors')
  const palette = getColorPalette()

  containers.forEach((container) => {
    const canvas = container.querySelector(`.${CHART_CANVAS_CLASS}`)
    const specPre = container.querySelector('.chart-render-spec')
    const loadingEl = container.querySelector(`.${CHART_LOADING_CLASS}`)

    if (!canvas || !specPre) return

    let option
    try {
      // textContent 自动解码 HTML 实体，还原原始 JSON
      option = JSON.parse(specPre.textContent)
    } catch (error) {
      console.error('chart:render JSON 解析失败:', error)
      if (loadingEl) loadingEl.textContent = '图表数据格式错误'
      container.dataset.chartError = 'true'
      return
    }

    // 注入 Yuxi 调色盘颜色（不覆盖用户显式指定的 color）
    if (!option.color) {
      option.color = palette
    }

    // 隐藏加载占位
    if (loadingEl) loadingEl.style.display = 'none'

    const chartId = `chart-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    const chart = echarts.init(canvas)
    chart.setOption(option)

    container.dataset.chartInit = 'true'
    container.dataset.chartId = chartId
    chartInstances.set(chartId, { chart, container })
  })
}

/**
 * 清理不再连接在 DOM 中的图表实例，释放 ECharts 资源。
 */
export function cleanupChartInstances(root, chartInstances) {
  for (const [id, entry] of chartInstances) {
    if (!root || !entry.container.isConnected || !root.contains(entry.container)) {
      entry.chart.dispose()
      chartInstances.delete(id)
    }
  }
}

/**
 * 处理窗口 resize，自适应调整所有活跃图表尺寸。
 */
export function resizeChartInstances(chartInstances) {
  for (const [, entry] of chartInstances) {
    if (entry.container.isConnected) {
      entry.chart.resize()
    }
  }
}
