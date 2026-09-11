---
name: dashi-ppt
description: "制作 PPT、演示文稿、幻灯片、汇报材料时使用。基于预置视觉主题组合页面，生成可离线打开、可在浏览器编辑的 HTML 演示，支持导出 PPTX / PDF 文件。"
---

# Dashi PPT

当用户需要制作 PPT、演示文稿、幻灯片、汇报材料、pitch deck 或任何形式的多页演示时，使用此 Skill。

## 工作流程

### 第一步：明确需求

向用户确认：
- 演示主题和目的
- 目标受众（内部汇报 / 客户提案 / 教学培训等）
- 大致页数或内容大纲
- 风格偏好（商务正式 / 简约清新 / 科技感等）

### 第二步：安装生成器

在沙盒中安装 dashi-ppt 生成器：

```bash
cd /home/gem/project && npm init -y && npm install dashi-ppt
```

如果安装失败，提示用户检查网络或使用镜像源：

```bash
cd /home/gem/project && npm install dashi-ppt --registry=https://registry.npmmirror.com
```

### 第三步：准备内容 JSON

将用户的文档、大纲或自然语言需求整理为 dashi-ppt 所需的 JSON 结构。JSON 应包含：

- `title`：演示文稿标题
- `slides`：页面数组，每页包含 `layout`（版式类型）和内容字段
- `theme`：主题名称（可选，用户未指定时先展示主题列表供选择）

### 第四步：生成演示文稿

运行生成器：

```bash
cd /home/gem/project && npx dashi-ppt generate input.json -o output/
```

生成的 HTML 文件：
- 可离线在浏览器中打开
- 每页带有编辑控制台，用户可直接修改文字、布局、图表、配色
- 内置多套视觉主题和大量版式，页面风格一致

### 第五步：交付与导出

1. 将生成的 HTML 文件通过 `present_artifacts` 展示给用户
2. 告知用户支持的导出格式：
   - **HTML**：离线浏览，浏览器编辑
   - **PPTX**：可编辑的 PowerPoint 文件
   - **PDF**：只读文档

如果用户需要切换主题：

```bash
cd /home/gem/project && npx dashi-ppt theme-switch output/presentation.html --theme <theme-name>
```

## 内置资源

- **12 套视觉主题**：覆盖商务、科技、简约、学术等风格
- **1020 个页面版式**：目录、分析模型、图表、卡片、时间线等
- **8576 个可调控件**：文本、图片、图表、图标等

## 注意事项

- 生成后的 HTML 演示文稿可在浏览器中直接编辑，无需专业软件
- 主题选择可在生成前预览，也可生成后整体切换
- 导出 PPTX 文件保留编辑能力，可在 PowerPoint 或 WPS 中继续修改
- 如果用户只需要简单的可视化内容（不超过 1 页、无导出需求），优先考虑 `html-preview` skill
