<template>
  <div class="workflow-editor">
    <!-- 顶部工具栏 -->
    <div class="editor-toolbar">
      <div class="toolbar-left">
        <a-button @click="goBack">
          <template #icon><ArrowLeft /></template>
        </a-button>
        <a-input
          v-if="workflow"
          v-model:value="workflow.name"
          class="workflow-name-input"
          @change="markDirty"
        />
        <a-tag v-if="workflow?.is_builtin" color="gold">内置</a-tag>
        <a-tag v-if="isDirty" color="orange">未保存</a-tag>
      </div>
      <div class="toolbar-right">
        <a-button @click="openRunHistory">
          <template #icon><History /></template>
          运行历史
        </a-button>
        <a-button @click="handleRunClick" :disabled="businessNodeCount === 0 || running">
          <template #icon><Play /></template>
          运行
        </a-button>
        <a-button type="primary" @click="saveWorkflow" :loading="saving">
          <template #icon><Save /></template>
          保存
        </a-button>
      </div>
    </div>

    <!-- 编辑器主体 -->
    <div class="editor-body" v-if="workflow">
      <!-- 画布占满全部空间 -->
      <div class="flow-canvas">
        <VueFlow
          v-model="flowElements"
          :default-viewport="{ zoom: 1, x: 0, y: 0 }"
          :min-zoom="0.2"
          :max-zoom="4"
          :connection-radius="30"
          :delete-key-code="['Backspace', 'Delete']"
          @node-click="onNodeClick"
          @connect="onConnect"
          @nodes-change="onNodesChange"
          @edges-change="onEdgesChange"
          @drop="onDrop"
          @dragover="onDragOver"
        >
          <Background :gap="16" pattern-color="#e5e7eb" />
          <Controls />
          <MiniMap :node-color="getMiniMapColor" />
          <template #node-workflow="nodeProps">
            <WorkflowNode :data="nodeProps.data" />
          </template>
          <template #edge-workflow="edgeProps">
            <WorkflowEdge v-bind="edgeProps" />
          </template>
        </VueFlow>

        <!-- 空画布提示 -->
        <div v-if="businessNodeCount === 0" class="canvas-empty-hint">
          <Inbox :size="48" stroke-width="1" color="#d1d5db" />
          <p>从底部拖拽节点到此处，并从「开始」连出流程</p>
        </div>

        <!-- 浮动：全局设置按钮 -->
        <div class="floating-settings-btn" @click="showSettings = !showSettings">
          <Settings :size="18" />
        </div>

        <!-- 浮动：全局设置面板 -->
        <div class="floating-settings-panel" v-if="showSettings">
          <div class="panel-header">
            <span>全局设置</span>
            <a-button size="small" type="text" @click="showSettings = false">
              <template #icon><X :size="14" /></template>
            </a-button>
          </div>
          <div class="settings-content">
            <div class="settings-row">
              <span class="settings-label">全局变量</span>
            </div>
            <div v-for="(gv, idx) in globalVariables" :key="idx" class="global-var-item">
              <a-input
                v-model:value="gv.name"
                placeholder="变量名（英文）"
                size="small"
                @change="markDirty"
              />
              <a-input
                v-model:value="gv.label"
                placeholder="中文名称"
                size="small"
                @change="markDirty"
              />
              <a-input
                v-model:value="gv.default"
                placeholder="默认值"
                size="small"
                @change="markDirty"
              />
              <a-button size="small" type="text" danger @click="removeGlobalVariable(idx)">
                <template #icon><Trash2 :size="12" /></template>
              </a-button>
            </div>
            <div v-if="globalVariables.length === 0" class="panel-hint">暂无全局变量</div>
            <a-button size="small" block @click="addGlobalVariable" style="margin-bottom: 12px;">
              <template #icon><Plus :size="12" /></template>
              添加变量
            </a-button>
          </div>
        </div>

        <!-- 浮动：步骤编辑抽屉 -->
        <div class="step-drawer" v-if="selectedStep" :class="{ collapsed: stepPanelCollapsed }">
          <div class="panel-header">
            <div class="panel-header-left">
              <a-button
                size="small"
                type="text"
                @click="stepPanelCollapsed = !stepPanelCollapsed"
                :title="stepPanelCollapsed ? '展开' : '收起'"
              >
                <template #icon><ChevronRight v-if="stepPanelCollapsed" :size="14" /><ChevronLeft v-else :size="14" /></template>
              </a-button>
              <span>编辑步骤</span>
            </div>
            <div class="panel-header-actions">
              <a-button
                v-if="!isBoundaryNode(selectedStep.id)"
                size="small"
                type="text"
                danger
                @click="confirmRemoveStep(selectedStep.id)"
              >
                <template #icon><Trash2 :size="14" /></template>
              </a-button>
            </div>
          </div>
          <div class="step-form" v-show="!stepPanelCollapsed">
            <a-form layout="vertical">
              <div class="node-type-badge">
                <component :is="getStepIcon(selectedStep.type)" :size="16" :stroke-width="1.5" />
                <span>{{ allStepTypeLabels[selectedStep.type] || selectedStep.type }}</span>
              </div>

              <!-- 开始步骤：编辑输入变量（保存到 definition.variables） -->
              <template v-if="selectedStep.type === 'start'">
                <a-divider>输入变量</a-divider>
                <div v-for="(v, idx) in variables" :key="idx" class="start-variable-item">
                  <a-input
                    v-model:value="v.name"
                    placeholder="变量名（英文）"
                    size="small"
                    @change="markDirty"
                  />
                  <a-input
                    v-model:value="v.label"
                    placeholder="中文名称"
                    size="small"
                    @change="markDirty"
                  />
                  <a-input
                    v-model:value="v.default"
                    placeholder="默认值"
                    size="small"
                    @change="markDirty"
                  />
                  <a-button size="small" type="text" danger @click="removeVariable(idx)">
                    <template #icon><Trash2 :size="12" /></template>
                  </a-button>
                </div>
                <div v-if="variables.length === 0" class="empty-variables">
                  暂无输入变量
                </div>
                <a-button size="small" block @click="addVariable">
                  <template #icon><Plus :size="12" /></template>
                  添加变量
                </a-button>
              </template>

              <!-- 结束步骤：编辑最终输出 -->
              <template v-else-if="selectedStep.type === 'end'">
                <a-form-item label="输出格式">
                  <a-select
                    v-model:value="selectedStep.format"
                    placeholder="Markdown（默认）"
                    allowClear
                    @change="markDirty"
                  >
                    <a-select-option value="markdown">Markdown</a-select-option>
                    <a-select-option value="text">纯文本</a-select-option>
                    <a-select-option value="json">JSON</a-select-option>
                  </a-select>
                </a-form-item>

                <!-- 可引用变量 -->
                <div v-if="availableVariables.length > 0" class="var-panel">
                  <div class="var-panel-title">可引用变量</div>
                  <div v-for="group in availableVariables" :key="group.label" class="var-group">
                    <div
                      class="var-group-header"
                      :class="{ 'var-group-expanded': expandedVarGroup === group.label }"
                      @click="toggleVarGroup(group.label)"
                    >
                      <span class="var-group-arrow">{{ expandedVarGroup === group.label ? '▾' : '▸' }}</span>
                      <span class="var-group-label">{{ group.label }}</span>
                      <span class="var-group-count">{{ group.variables.length }}</span>
                    </div>
                    <div v-if="expandedVarGroup === group.label" class="var-group-body">
                      <div
                        v-for="v in group.variables"
                        :key="v.name"
                        class="var-tag"
                        @click.stop="insertVariable(v.name)"
                        :title="`点击插入 {{${v.name}}}`"
                      >
                        <span v-if="v.label" class="var-tag-label">{{ v.label }}</span>
                        <span class="var-tag-name">{{ v.name }}</span>
                        <span v-if="v.desc && !v.label" class="var-tag-desc">{{ v.desc }}</span>
                      </div>
                    </div>
                  </div>
                </div>

                <a-form-item label="输出模板">
                  <a-textarea
                    v-model:value="selectedStep.template"
                    :rows="6"
                    placeholder="最终输出模板，可使用 {{变量名}}；留空则汇总上游 output_key 结果"
                    @change="markDirty"
                    @focus="setActiveField('template')"
                  />
                </a-form-item>
              </template>

              <!-- 业务步骤 -->
              <template v-else>
                <a-form-item label="名称">
                  <a-input v-model:value="selectedStep.name" @change="onNameChange" />
                </a-form-item>

                <!-- 引用 Agent：名称下方，搜索下拉选择 -->
                <a-form-item v-if="selectedStep.type === 'llm'" label="引用 Agent（可选）">
                  <a-select
                    v-model:value="selectedStep.agent_slug"
                    show-search
                    allow-clear
                    placeholder="搜索并选择 Agent，留空使用默认模型"
                    :filter-option="agentFilterOption"
                    :options="agentSelectOptions"
                    @change="markDirty"
                  />
                </a-form-item>

                <!-- 可用变量面板：先选节点，再展开该节点的变量 -->
                <div v-if="availableVariables.length > 0" class="var-panel">
                  <div class="var-panel-title">可引用变量</div>
                  <div v-for="group in availableVariables" :key="group.label" class="var-group">
                    <div
                      class="var-group-header"
                      :class="{ 'var-group-expanded': expandedVarGroup === group.label }"
                      @click="toggleVarGroup(group.label)"
                    >
                      <span class="var-group-arrow">{{ expandedVarGroup === group.label ? '▾' : '▸' }}</span>
                      <span class="var-group-label">{{ group.label }}</span>
                      <span class="var-group-count">{{ group.variables.length }}</span>
                    </div>
                    <div v-if="expandedVarGroup === group.label" class="var-group-body">
                      <div
                        v-for="v in group.variables"
                        :key="v.name"
                        class="var-tag"
                        @click.stop="insertVariable(v.name)"
                        :title="`点击插入 {{${v.name}}}`"
                      >
                        <span v-if="v.label" class="var-tag-label">{{ v.label }}</span>
                        <span class="var-tag-name">{{ v.name }}</span>
                        <span v-if="v.desc && !v.label" class="var-tag-desc">{{ v.desc }}</span>
                      </div>
                    </div>
                  </div>
                </div>

                <!-- LLM 步骤特有字段 -->
                <template v-if="selectedStep.type === 'llm'">
                  <a-form-item :label="selectedStep.agent_slug ? '任务指令' : 'Prompt'">
                    <div data-var-field="prompt">
                      <a-textarea
                        v-model:value="selectedStep.prompt"
                        :rows="6"
                        :placeholder="selectedStep.agent_slug
                          ? '告诉 Agent 这一步要做什么，可使用 {{变量名}} 引用上游输出'
                          : '输入 prompt，可使用 {{变量名}} 引用上下文变量'"
                        @change="markDirty"
                        @focus="setActiveField('prompt')"
                      />
                    </div>
                  </a-form-item>
                  <template v-if="!selectedStep.agent_slug">
                    <a-form-item label="模型规格（可选）">
                      <a-input
                        v-model:value="selectedStep.model_spec"
                        placeholder="如 deepseek/deepseek-chat；留空用系统默认"
                        @change="markDirty"
                      />
                    </a-form-item>
                  </template>
                  <div v-else class="panel-hint">已引用 Agent「{{ agentNameMap[selectedStep.agent_slug] || selectedStep.agent_slug }}」，角色设定、知识库和工具由 Agent 提供</div>
                </template>

                <!-- Tool 步骤特有字段 -->
                <template v-if="selectedStep.type === 'tool'">
                  <a-form-item label="工具名称">
                    <a-input
                      v-model:value="selectedStep.tool_name"
                      placeholder="工具 slug"
                      @change="markDirty"
                    />
                  </a-form-item>
                  <a-form-item label="工具参数 (JSON)">
                    <a-textarea
                      v-model:value="toolParamsText"
                      :rows="4"
                      placeholder='{"key": "value"}'
                      @change="markDirty"
                    />
                  </a-form-item>
                </template>

                <!-- HTTP 步骤特有字段 -->
                <template v-if="selectedStep.type === 'http'">
                  <a-form-item label="URL">
                    <div data-var-field="url">
                      <a-input v-model:value="selectedStep.url" placeholder="https://..." @change="markDirty" @focus="setActiveField('url')" />
                    </div>
                  </a-form-item>
                  <a-form-item label="Method">
                    <a-select v-model:value="selectedStep.method" @change="markDirty">
                      <a-select-option value="GET">GET</a-select-option>
                      <a-select-option value="POST">POST</a-select-option>
                      <a-select-option value="PUT">PUT</a-select-option>
                      <a-select-option value="DELETE">DELETE</a-select-option>
                    </a-select>
                  </a-form-item>
                  <a-form-item label="请求头 (JSON)">
                    <a-textarea
                      v-model:value="httpHeadersText"
                      :rows="3"
                      placeholder='{"Content-Type": "application/json", "Authorization": "Bearer ..."}'
                      @change="markDirty"
                    />
                  </a-form-item>
                  <a-form-item label="请求体 (JSON)">
                    <div data-var-field="body">
                      <a-textarea
                        v-model:value="httpBodyText"
                        :rows="4"
                        placeholder='{"key": "{{变量名}}"}'
                        @change="markDirty"
                        @focus="setActiveField('body')"
                      />
                    </div>
                  </a-form-item>
                  <a-form-item label="超时（秒）">
                    <a-input-number
                      v-model:value="selectedStep.timeout"
                      :min="1"
                      :max="300"
                      placeholder="30"
                      @change="markDirty"
                    />
                  </a-form-item>
                </template>

                <!-- Condition 步骤特有字段：多分支配置 -->
                <template v-if="selectedStep.type === 'condition'">
                  <a-form-item label="条件变量">
                    <div data-var-field="condition">
                      <a-input
                        v-model:value="selectedStep.condition"
                        placeholder="{{变量名}}"
                        @change="markDirty"
                        @focus="setActiveField('condition')"
                      />
                    </div>
                  </a-form-item>
                  <a-divider>分支列表</a-divider>
                  <div
                    v-for="(branch, idx) in selectedStep.branches"
                    :key="branch.id"
                    class="condition-branch-row"
                  >
                    <div class="condition-branch-header">
                      <span class="condition-branch-dot" :style="{ background: branchColors[idx % branchColors.length] }"></span>
                      <a-input
                        :value="branch.label"
                        placeholder="分支名称"
                        class="condition-branch-name-input"
                        @change="(e) => updateBranchLabel(branch.id, e.target.value)"
                      />
                      <a-button
                        type="text"
                        size="small"
                        danger
                        :disabled="selectedStep.branches.length <= 2"
                        @click="removeBranch(branch.id)"
                      >
                        <template #icon><Trash2 :size="14" /></template>
                      </a-button>
                    </div>
                    <a-input
                      :value="branch.match"
                      placeholder="匹配值（留空则为默认分支）"
                      class="condition-branch-match-input"
                      @change="(e) => updateBranchMatch(branch.id, e.target.value)"
                    />
                  </div>
                  <a-button type="dashed" block class="condition-add-branch-btn" @click="addBranch">
                    <template #icon><Plus :size="14" /></template>
                    添加分支
                  </a-button>
                </template>

                <!-- Approval 步骤特有字段 -->
                <template v-if="selectedStep.type === 'approval'">
                  <a-form-item label="审批提示">
                    <a-textarea
                      v-model:value="selectedStep.approval_prompt"
                      :rows="3"
                      placeholder="展示给审批人的提示信息"
                      @change="markDirty"
                    />
                  </a-form-item>
                </template>

                <!-- Script 步骤特有字段 -->
                <template v-if="selectedStep.type === 'script'">
                  <a-form-item label="脚本代码">
                    <a-tabs v-model:activeKey="scriptEditorTab" size="small" class="script-editor-tabs">
                      <a-tab-pane key="ai" tab="AI 辅助">
                        <div class="ai-code-gen-panel">
                          <a-textarea
                            v-model:value="aiPrompt"
                            :rows="3"
                            placeholder="描述你需要的脚本功能，例如：从 context 中读取 user_name，返回一个问候语对象"
                          />
                          <div class="ai-code-gen-actions">
                            <a-button
                              type="primary"
                              size="small"
                              :loading="aiGenerating"
                              :disabled="!aiPrompt?.trim()"
                              @click="generateAiCode"
                            >
                              生成代码
                            </a-button>
                            <span v-if="aiGenerating" class="ai-gen-hint">AI 正在生成...</span>
                          </div>
                          <div v-if="aiGeneratedCode" class="ai-generated-preview">
                            <div class="ai-preview-header">
                              <span>生成结果</span>
                              <div>
                                <a-button size="small" @click="aiGeneratedCode = ''">重新生成</a-button>
                                <a-button type="primary" size="small" @click="applyAiCode">应用到编辑器</a-button>
                              </div>
                            </div>
                            <pre class="ai-preview-code">{{ aiGeneratedCode }}</pre>
                          </div>
                        </div>
                      </a-tab-pane>
                      <a-tab-pane key="manual" tab="手写">
                        <div data-var-field="code">
                          <Codemirror
                            :value="selectedStep.code"
                            :extensions="cmExtensions"
                            :style="{ height: '260px', fontSize: '13px' }"
                            @change="(val) => { selectedStep.code = val; markDirty() }"
                            @focus="setActiveField('code')"
                          />
                        </div>
                      </a-tab-pane>
                    </a-tabs>
                  </a-form-item>
                  <a-form-item>
                    <a-button
                      type="primary"
                      ghost
                      :loading="scriptTesting"
                      @click="testRunScript"
                    >
                      <template #icon><Play :size="14" /></template>
                      模拟运行
                    </a-button>
                  </a-form-item>
                  <div v-if="scriptTestResult !== null" class="script-test-result">
                    <div class="script-test-result-header">
                      <span>运行结果</span>
                      <a-button type="text" size="small" @click="scriptTestResult = null">
                        <template #icon><X :size="12" /></template>
                      </a-button>
                    </div>
                    <pre :class="['script-test-output', { 'script-test-error': scriptTestError }]">{{ scriptTestResult }}</pre>
                  </div>
                </template>

                <!-- Output 步骤特有字段 -->
                <template v-if="selectedStep.type === 'output'">
                  <a-form-item label="输出格式">
                    <a-select v-model:value="selectedStep.format" @change="markDirty">
                      <a-select-option value="markdown">Markdown</a-select-option>
                      <a-select-option value="html">HTML</a-select-option>
                      <a-select-option value="json">JSON</a-select-option>
                    </a-select>
                  </a-form-item>
                  <a-form-item label="模板">
                    <div data-var-field="template">
                      <a-textarea
                        v-model:value="selectedStep.template"
                        :rows="6"
                        placeholder="输出模板，可使用 {{变量名}}"
                        @change="markDirty"
                        @focus="setActiveField('template')"
                      />
                    </div>
                  </a-form-item>
                  <a-form-item label="交付渠道">
                    <a-select
                      v-model:value="selectedStep.delivery"
                      mode="multiple"
                      placeholder="选择交付方式（可多选）"
                      allowClear
                      @change="markDirty"
                    >
                      <a-select-option value="page">页面展示</a-select-option>
                      <a-select-option value="dingtalk">钉钉</a-select-option>
                      <a-select-option value="wecom">企业微信</a-select-option>
                    </a-select>
                  </a-form-item>
                </template>

                <!-- 输出变量名（所有业务步骤通用） -->
                <a-divider>输出</a-divider>
                <a-form-item label="输出变量名 (output_key)">
                  <a-input
                    v-model:value="selectedStep.output_key"
                    placeholder="将步骤输出写入此变量名，供下游步骤引用"
                    @change="markDirty"
                  />
                </a-form-item>
                <a-form-item label="输出中文名称 (output_label)">
                  <a-input
                    v-model:value="selectedStep.output_label"
                    placeholder="可选，用于在变量选择器中显示中文名称"
                    @change="markDirty"
                  />
                </a-form-item>

                <!-- 循环配置（默认收起） -->
                <div class="loop-config-section">
                  <div class="loop-config-header" @click="loopConfigExpanded = !loopConfigExpanded">
                    <span class="loop-config-arrow">{{ loopConfigExpanded ? '▾' : '▸' }}</span>
                    <span>循环配置</span>
                    <span v-if="selectedStep.loop && selectedStep.loop.back_to" class="loop-config-badge">已配置</span>
                    <span v-else-if="selectedStep.loop && !selectedStep.loop.back_to" class="loop-config-badge loop-config-badge--warn">待完善</span>
                    <span
                      class="loop-config-help-btn"
                      @click.stop="showLoopHelp = true"
                      title="配置指南"
                    >
                      <HelpCircle :size="14" />
                    </span>
                  </div>
                  <div v-if="loopConfigExpanded" class="loop-config-body">
                    <div class="loop-config-intro">
                      <p>循环配置可让步骤执行后回到前面某个步骤重新执行，适用于审批复核、数据校验重试等需要反复迭代的场景。</p>
                    </div>
                    <template v-if="selectedStep.loop">
                    <a-form-item label="回退到步骤" extra="循环结束时将回到该步骤重新执行，不可选择开始/结束节点">
                      <a-select
                        v-model:value="selectedStep.loop.back_to"
                        placeholder="选择循环回退的目标步骤"
                        allow-clear
                        @change="markDirty"
                      >
                        <a-select-option
                          v-for="s in steps.filter(s => s.id !== selectedStep.id && !isBoundaryNode(s.id))"
                          :key="s.id"
                          :value="s.id"
                        >
                          {{ s.name || s.id }}
                        </a-select-option>
                      </a-select>
                    </a-form-item>
                    <a-form-item label="最大循环次数" extra="防止无限循环的安全上限，达到后强制退出循环（1-20）">
                      <a-input-number
                        v-model:value="selectedStep.loop.max_iterations"
                        :min="1"
                        :max="20"
                        placeholder="3"
                        @change="markDirty"
                      />
                    </a-form-item>
                    <a-form-item label="退出条件（可选）" extra="满足条件时提前退出循环，支持变量引用和 contains/equals 等表达式">
                      <div data-var-field="exit_condition">
                        <a-input
                          v-model:value="selectedStep.loop.exit_condition"
                          placeholder="如 {{review_result}} contains APPROVED"
                          @change="markDirty"
                          @focus="setActiveField('exit_condition')"
                        />
                      </div>
                    </a-form-item>
                    <a-button
                      type="text"
                      size="small"
                      danger
                      @click="selectedStep.loop = null; markDirty()"
                    >
                      <template #icon><Trash2 :size="12" /></template>
                      移除循环配置
                    </a-button>
                    </template>
                    <a-button
                      v-if="!selectedStep.loop"
                      type="dashed"
                      size="small"
                      block
                      @click="selectedStep.loop = { back_to: null, max_iterations: 3, exit_condition: null }; markDirty()"
                    >
                      <template #icon><Plus :size="12" /></template>
                      添加循环配置
                    </a-button>
                  </div>
                </div>

              </template>
            </a-form>
          </div>
        </div>
      </div>

      <!-- 底部：节点工具栏 -->
      <div class="node-palette-bar">
        <div
          v-for="(desc, type) in stepTypes"
          :key="type"
          class="palette-bar-item"
          draggable="true"
          @dragstart="(e) => onDragStart(e, type)"
        >
          <div class="palette-bar-icon">
            <component :is="getStepIcon(type)" :size="16" :stroke-width="1.5" />
          </div>
          <span class="palette-bar-label">{{ desc }}</span>
        </div>
      </div>
    </div>

    <!-- 运行弹窗 -->
    <a-modal
      v-model:open="showRunModal"
      title="运行工作流"
      @ok="handleRun"
      :confirmLoading="running"
    >
      <a-form layout="vertical">
        <a-form-item v-for="v in variables" :key="v.name" :label="v.name">
          <a-input v-model:value="runInputs[v.name]" :placeholder="v.default || ''" />
        </a-form-item>
        <div v-if="variables.length === 0">此工作流无输入变量</div>
      </a-form>
    </a-modal>

    <!-- 运行历史弹窗 -->
    <a-modal
      v-model:open="showRunHistory"
      title="运行历史"
      :footer="null"
      :width="640"
    >
      <div v-if="runHistoryLoading" style="text-align: center; padding: 24px;">
        <a-spin tip="加载中..." />
      </div>
      <div v-else-if="runHistoryList.length === 0" style="text-align: center; padding: 24px; color: var(--gray-400);">
        暂无运行记录
      </div>
      <div v-else class="run-history-list">
        <div
          v-for="run in runHistoryList"
          :key="run.id"
          class="run-history-item"
          @click="viewRunDetail(run)"
        >
          <div class="run-history-item-main">
            <a-tag :color="run.status === 'completed' ? 'green' : run.status === 'failed' ? 'red' : 'blue'" size="small">
              {{ run.status }}
            </a-tag>
            <span class="run-history-time">{{ formatRunTime(run.created_at) }}</span>
            <a-button
              v-if="run.status === 'pending' || run.status === 'running'"
              size="small"
              danger
              @click.stop="handleCancelRun(run.id)"
              :loading="run._cancelling"
            >
              强制关闭
            </a-button>
          </div>
          <div v-if="run.error_message" class="run-history-error">{{ run.error_message }}</div>
        </div>
      </div>
    </a-modal>

    <!-- 运行结果弹窗 -->
    <a-modal
      v-model:open="showRunResult"
      title="运行结果"
      :footer="null"
      :width="672"
      :body-style="{ maxHeight: '85vh', overflow: 'auto' }"
      wrap-class-name="run-result-modal"
      @cancel="onRunResultClose"
    >
      <div v-if="runResultData">
        <div class="run-result-status">
          <a-tag :color="runResultData.status === 'completed' ? 'green' : runResultData.status === 'failed' ? 'red' : 'blue'">
            {{ runResultData.status === 'running' ? '执行中...' : runResultData.status === 'completed' ? '已完成' : runResultData.status === 'failed' ? '已失败' : runResultData.status }}
          </a-tag>
          <span v-if="runResultData.status === 'running' && runResultData.step_runs" class="run-result-progress">
            步骤 {{ completedStepCount }}/{{ runResultData.step_runs.length }}
          </span>
          <span v-if="runResultData.error_message" class="run-result-error-msg">{{ runResultData.error_message }}</span>
          <a-button
            v-if="runResultData.status === 'pending' || runResultData.status === 'running'"
            size="small"
            danger
            :loading="cancellingRun"
            @click="handleCancelRun(runResultData.id)"
            style="margin-left: auto;"
          >
            强制关闭
          </a-button>
        </div>
        <!-- 步骤列表（实时显示已完成的步骤） -->
        <div v-if="runResultData.step_runs && runResultData.step_runs.length > 0" class="run-result-steps">
          <div
            v-for="sr in runResultData.step_runs"
            :key="sr.id"
            :ref="el => setStepRef(el, sr.id)"
            :class="['run-result-step', { 'run-result-step-active': getEffectiveStatus(sr) === 'running', 'run-result-step-done': getEffectiveStatus(sr) === 'completed', 'run-result-step-failed': getEffectiveStatus(sr) === 'failed' }]"
          >
            <div class="run-result-step-header">
              <span class="run-result-step-icon">
                <CheckCircleOutlined v-if="getEffectiveStatus(sr) === 'completed'" style="color: var(--success-500, #52c41a);" />
                <CloseCircleOutlined v-else-if="getEffectiveStatus(sr) === 'failed'" style="color: var(--danger-500, #ef4444);" />
                <LoadingOutlined v-else-if="getEffectiveStatus(sr) === 'running'" style="color: var(--primary-500, #1677ff);" />
                <ClockCircleOutlined v-else style="color: var(--gray-400);" />
              </span>
              <a-tag :color="getEffectiveStatus(sr) === 'completed' ? 'green' : getEffectiveStatus(sr) === 'failed' ? 'red' : getEffectiveStatus(sr) === 'running' ? 'blue' : 'default'" size="small">
                {{ getEffectiveStatus(sr) === 'completed' ? '已完成' : getEffectiveStatus(sr) === 'running' ? '执行中' : getEffectiveStatus(sr) === 'failed' ? '失败' : '等待中' }}
              </a-tag>
              <span class="run-result-step-name">{{ stepNameMap[sr.step_id] || sr.step_id }}</span>
            </div>
            <div v-if="hasStepOutput(sr)" class="run-result-step-output">
              <pre>{{ formatRunOutput(sr.output_payload || sr.output) }}</pre>
            </div>
            <div v-if="sr.error_message" class="run-result-step-error">{{ sr.error_message }}</div>
          </div>
        </div>
        <!-- 否则展示 context 中的变量 -->
        <div v-else-if="runResultData.context && Object.keys(runResultData.context).length > 0">
          <div class="run-result-context-title">输出变量</div>
          <div v-for="(val, key) in runResultData.context" :key="key" class="run-result-step">
            <div class="run-result-step-header">
              <span class="run-result-step-name">{{ key }}</span>
            </div>
            <div class="run-result-step-output">
              <pre>{{ formatRunOutput(val) }}</pre>
            </div>
          </div>
        </div>
        <div v-else style="text-align: center; padding: 16px; color: var(--gray-400);">等待执行...</div>
      </div>
      <div v-else style="text-align: center; padding: 24px;">
        <a-spin tip="启动中..." />
      </div>
    </a-modal>

    <!-- 循环配置指南弹窗 -->
    <a-modal
      v-model:open="showLoopHelp"
      title="循环配置指南"
      :footer="null"
      :width="560"
      class="loop-help-modal"
    >
      <div class="loop-help-content">
        <h4>什么是循环配置？</h4>
        <p>循环配置允许你将某个步骤标记为「循环步骤」，该步骤执行完成后会自动回到前面指定的步骤重新执行，直到满足退出条件或达到最大循环次数。</p>

        <h4>配置项说明</h4>
        <ul>
          <li><strong>回退到步骤</strong> — 循环的起点，当前步骤执行完毕后将回到该步骤重新开始。不可选择开始/结束节点。</li>
          <li><strong>最大循环次数</strong> — 安全上限，防止无限循环。达到上限后无论条件是否满足都会强制退出（范围 1-20）。</li>
          <li><strong>退出条件</strong> — 可选，填写表达式，当表达式为真时提前退出循环。支持变量引用和 <code>contains</code> / <code>equals</code> 等操作符。</li>
        </ul>

        <h4>典型场景</h4>
        <div class="loop-help-example">
          <div class="loop-help-example-title">场景一：审批复核循环</div>
          <p>步骤 A（提交申请）→ 步骤 B（审批）→ 步骤 C（复核）</p>
          <p>在步骤 C 配置循环：回退到步骤 B，退出条件 <code>{{review_result}} contains REJECTED</code>，最大循环 3 次。</p>
          <p>效果：审批被驳回时回到步骤 B 重新审批，最多重试 3 次。</p>
        </div>
        <div class="loop-help-example">
          <div class="loop-help-example-title">场景二：数据校验重试</div>
          <p>步骤 A（获取数据）→ 步骤 B（校验）→ 步骤 C（处理）</p>
          <p>在步骤 B 配置循环：回退到步骤 A，退出条件 <code>{{validation_status}} equals PASS</code>，最大循环 5 次。</p>
          <p>效果：校验不通过时重新获取数据，最多重试 5 次。</p>
        </div>

        <h4>注意事项</h4>
        <ul>
          <li>循环范围是「回退步骤 → 当前步骤」之间的所有步骤</li>
          <li>每次循环会重新执行范围内的所有步骤，历史结果会被覆盖</li>
          <li>建议始终设置合理的最大循环次数，避免无限循环</li>
          <li>退出条件中可使用 <code>{{ 变量名 }}</code> 引用步骤输出变量</li>
        </ul>
      </div>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message, Modal } from 'ant-design-vue'
import { VueFlow, useVueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import { ArrowLeft, Play, Save, Plus, Trash2, Inbox, Settings, X, ChevronLeft, ChevronRight, History, HelpCircle } from '@lucide/vue'
import { Bot, Wrench, Globe, GitBranch, UserCheck, Code2, Send, Flag } from '@lucide/vue'
import { CheckCircleOutlined, CloseCircleOutlined, LoadingOutlined, ClockCircleOutlined } from '@ant-design/icons-vue'
import WorkflowNode from '@/components/workflow/WorkflowNode.vue'
import WorkflowEdge from '@/components/workflow/WorkflowEdge.vue'
import { workflowApi } from '@/apis/workflow_api'
import { agentApi } from '@/apis/agent_api'

import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import '@vue-flow/minimap/dist/style.css'

// CodeMirror 6 代码编辑器
import { Codemirror } from 'vue-codemirror'
import { javascript } from '@codemirror/lang-javascript'
import { oneDark } from '@codemirror/theme-one-dark'

// CodeMirror 扩展配置
const cmExtensions = [
  javascript(),
  oneDark,
]

const route = useRoute()
const router = useRouter()

// 固定的开始/结束步骤：真实 step（type: start/end），负责输入与输出边界，
// id 固定且唯一，画布中不可删除，由首次加载迁移逻辑补齐
const START_NODE_ID = 'start'
const END_NODE_ID = 'end'
const isBoundaryNode = (id) => id === START_NODE_ID || id === END_NODE_ID

// 状态
const workflow = ref(null)
const saving = ref(false)
const running = ref(false)
const isDirty = ref(false)
const selectedStepId = ref(null)
const showRunModal = ref(false)
const runInputs = ref({})
const showSettings = ref(false)
const stepPanelCollapsed = ref(false)
const loopConfigExpanded = ref(false)
const showLoopHelp = ref(false)
const agentOptions = ref([])
const showRunResult = ref(false)
const runResultLoading = ref(true)
const runResultData = ref(null)
let runPollTimer = null
const showRunHistory = ref(false)
const runHistoryLoading = ref(false)
const runHistoryList = ref([])
const cancellingRun = ref(false)
const agentSelectOptions = computed(() =>
  agentOptions.value.map(a => ({
    value: a.slug,
    label: `${a.name} (${a.slug})`
  }))
)
const agentNameMap = computed(() => {
  const map = {}
  for (const a of agentOptions.value) {
    map[a.slug] = a.name
  }
  return map
})

// Vue Flow 元素
const flowElements = ref([])
// useVueFlow 依赖 inject，必须在 setup 顶层同步调用，不能放在 onMounted 中
const { project, fitView, onNodesInitialized, addEdges } = useVueFlow()

// 节点尺寸测量完成后自适应视口一次，保证打开页面时整个流程可见
let hasFitted = false
onNodesInitialized(() => {
  if (hasFitted) return
  hasFitted = true
  fitView({ padding: 0.15, duration: 200 })
})

// 步骤类型
const stepTypes = {
  llm: '大模型',
  tool: '工具调用',
  http: 'HTTP 请求',
  condition: '条件分支',
  approval: '人工审批',
  script: '脚本执行',
  output: '输出'
}

const allStepTypeLabels = {
  start: '开始',
  end: '结束',
  ...stepTypes
}

const stepIcons = {
  start: Play,
  llm: Bot,
  tool: Wrench,
  http: Globe,
  condition: GitBranch,
  approval: UserCheck,
  script: Code2,
  output: Send,
  end: Flag
}

const getStepIcon = (type) => stepIcons[type] || Bot

// 按步骤类型返回默认字段（确保 Vue 响应式能追踪到后续赋值）
function getStepDefaults(type) {
  switch (type) {
    case 'llm': return { prompt: '', agent_slug: '', model_spec: '' }
    case 'tool': return { tool_name: '', tool_params: {} }
    case 'http': return { url: '', method: 'GET', headers: {}, body: null, timeout: 30 }
    case 'condition': return { condition: '', branches: [{ id: 'b1', label: '分支 1', match: '' }, { id: 'b2', label: '分支 2', match: '' }] }
    case 'approval': return { approval_prompt: '' }
    case 'script': return { code: 'function main(context) {\n  // context 包含上游节点的输出变量\n  // 返回结果会作为该节点的 output\n  return { result: "Hello from script" }\n}', language: 'javascript' }
    case 'output': return { format: 'markdown', template: '', delivery: [] }
    default: return {}
  }
}

// 条件分支颜色调色板（与 WorkflowNode.vue 保持一致）
const branchColors = [
  '#10b981', '#f59e0b', '#3b82f6', '#ef4444',
  '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16'
]

// 条件分支管理函数
function addBranch() {
  if (!selectedStep.value || selectedStep.value.type !== 'condition') return
  if (!selectedStep.value.branches) selectedStep.value.branches = []
  const idx = selectedStep.value.branches.length + 1
  selectedStep.value.branches.push({
    id: `b_${Date.now()}`,
    label: `分支 ${idx}`,
    match: ''
  })
  // 同步到画布节点 data，让 Handle 立即刷新
  syncBranchesToNodeData(selectedStep.value.id, selectedStep.value.branches)
  markDirty()
}

function removeBranch(branchId) {
  if (!selectedStep.value || !selectedStep.value.branches) return
  if (selectedStep.value.branches.length <= 2) return
  selectedStep.value.branches = selectedStep.value.branches.filter(b => b.id !== branchId)
  syncBranchesToNodeData(selectedStep.value.id, selectedStep.value.branches)
  markDirty()
}

function updateBranchLabel(branchId, val) {
  if (!selectedStep.value?.branches) return
  const branch = selectedStep.value.branches.find(b => b.id === branchId)
  if (branch) {
    branch.label = val
    syncBranchesToNodeData(selectedStep.value.id, selectedStep.value.branches)
    markDirty()
  }
}

function updateBranchMatch(branchId, val) {
  if (!selectedStep.value?.branches) return
  const branch = selectedStep.value.branches.find(b => b.id === branchId)
  if (branch) {
    branch.match = val
    markDirty()
  }
}

// 将分支数据同步到画布节点的 data.branches，使 WorkflowNode 的 Handle 即时刷新
function syncBranchesToNodeData(stepId, branches) {
  const node = flowElements.value.find(e => e.id === stepId && !e.source && !e.target)
  if (node) {
    node.data = { ...node.data, branches: [...branches] }
  }
}

// 计算属性
const steps = computed(() => workflow.value?.definition?.steps || [])
// 步骤 ID → 中文名称映射（用于运行结果展示）
const stepNameMap = computed(() => {
  const map = {}
  for (const s of steps.value) {
    if (s?.id && s?.name) map[s.id] = s.name
  }
  return map
})
// 运行结果：已完成的步骤数（start 类型视为已完成）
const completedStepCount = computed(() => {
  if (!runResultData.value?.step_runs) return 0
  return runResultData.value.step_runs.filter(sr => sr.status === 'completed' || sr.step_type === 'start').length
})

// 获取步骤的有效状态（start 类型直接视为已完成）
function getEffectiveStatus(sr) {
  if (sr.step_type === 'start') return 'completed'
  return sr.status
}
// 判断步骤是否有有效输出（排除空对象 {}）
function hasStepOutput(sr) {
  const output = sr.output_payload || sr.output
  if (!output) return false
  if (typeof output === 'string') return output.trim() !== '' && output !== '{}'
  if (typeof output === 'object') return Object.keys(output).length > 0
  return true
}
// 步骤 DOM 引用（用于自动滚动）
const stepRefs = {}
function setStepRef(el, stepId) {
  if (el) stepRefs[stepId] = el
  else delete stepRefs[stepId]
}
// 自动滚动到当前执行的步骤
function scrollToActiveStep() {
  if (!runResultData.value?.step_runs) return
  const activeStep = runResultData.value.step_runs.find(sr => sr.status === 'running')
  if (activeStep && stepRefs[activeStep.step_id]) {
    stepRefs[activeStep.step_id].scrollIntoView({ behavior: 'smooth', block: 'center' })
  }
}
const variables = computed(() => workflow.value?.definition?.variables || [])
const globalVariables = computed(() => {
  if (!workflow.value?.definition) return []
  return workflow.value.definition.global_variables || []
})

const flowNodes = computed(() => flowElements.value.filter(e => !e.source && !e.target))
const flowEdges = computed(() => flowElements.value.filter(e => e.source && e.target))
// 空画布提示以业务步骤为准：start/end 边界步骤不算内容
const businessNodeCount = computed(() => flowNodes.value.filter(n => !isBoundaryNode(n.id)).length)

const selectedStep = computed(() => {
  if (!selectedStepId.value) return null
  return steps.value.find(s => s.id === selectedStepId.value)
})

// 递归追溯当前节点的所有上游步骤（沿 depends_on 链路）
function getUpstreamSteps(stepId, visited = new Set()) {
  const result = []
  const step = steps.value.find(s => s.id === stepId)
  if (!step?.depends_on) return result
  for (const depId of step.depends_on) {
    if (visited.has(depId)) continue
    visited.add(depId)
    const dep = steps.value.find(s => s.id === depId)
    if (dep && dep.type !== 'start' && dep.type !== 'end') {
      result.push(dep)
    }
    result.push(...getUpstreamSteps(depId, visited))
  }
  return result
}

// 当前节点可用的变量：全局输入变量 + 所有上游节点的 output_key
const availableVariables = computed(() => {
  if (!selectedStep.value) return []
  const groups = []

  // 1. 工作流全局输入变量
  if (variables.value.length > 0) {
    groups.push({
      label: '开始',
      variables: variables.value.map(v => ({
        name: typeof v === 'string' ? v : v.name,
        desc: typeof v === 'string' ? '' : (v.label || v.description || v.default || ''),
        label: typeof v === 'string' ? '' : (v.label || '')
      }))
    })
  }

  // 1.5 全局变量（来自全局设置）
  if (globalVariables.value.length > 0) {
    groups.push({
      label: '全局变量',
      variables: globalVariables.value.map(v => ({
        name: v.name,
        desc: v.label || v.default || '',
        label: v.label || ''
      }))
    })
  }

  // 2. 上游节点的输出变量（递归追溯所有连线链路）
  const upstream = getUpstreamSteps(selectedStep.value.id)
  // 去重并保留有 output_key 的节点
  const seen = new Set()
  const upstreamVars = []
  for (const step of upstream) {
    if (seen.has(step.id)) continue
    seen.add(step.id)
    if (step.output_key) {
      upstreamVars.push({
        name: step.output_key,
        desc: step.output_label || `${step.name || step.id} 的输出`,
        label: step.output_label || '',
        stepName: step.name || step.id,
        stepType: step.type
      })
    }
  }

  // 按步骤分组展示
  const byStep = new Map()
  for (const v of upstreamVars) {
    if (!byStep.has(v.stepName)) {
      byStep.set(v.stepName, { label: v.stepName, stepType: v.stepType, variables: [] })
    }
    byStep.get(v.stepName).variables.push({ name: v.name, desc: v.desc, label: v.label })
  }
  groups.push(...byStep.values())

  return groups
})

// 当前焦点所在的文本字段（用于变量插入）
const activeField = ref(null)

// 脚本测试运行状态
const scriptTesting = ref(false)
const scriptTestResult = ref(null)
const scriptTestError = ref(false)

async function testRunScript() {
  if (!selectedStep.value?.code) return
  scriptTesting.value = true
  scriptTestResult.value = null
  scriptTestError.value = false
  try {
    // 收集上游变量作为测试上下文
    const testContext = {}
    const upstream = getUpstreamSteps(selectedStep.value.id)
    for (const step of upstream) {
      if (step.output_key) testContext[step.output_key] = `<${step.name} 模拟值>`
    }
    // 加入工作流全局变量
    for (const v of variables.value) {
      const name = typeof v === 'string' ? v : v.name
      testContext[name] = `<${name} 模拟值>`
    }
    const res = await workflowApi.testScript(
      selectedStep.value.code,
      selectedStep.value.language || 'javascript',
      testContext
    )
    if (res.data?.error) {
      scriptTestError.value = true
      scriptTestResult.value = res.data.error
    } else {
      scriptTestResult.value = JSON.stringify(res.data?.result, null, 2)
    }
  } catch (err) {
    scriptTestError.value = true
    scriptTestResult.value = err.message || '执行失败'
  } finally {
    scriptTesting.value = false
  }
}

// 脚本编辑器 Tab 状态（手写 / AI 辅助）
const scriptEditorTab = ref('ai')
const aiPrompt = ref('')
const aiGenerating = ref(false)
const aiGeneratedCode = ref('')

async function generateAiCode() {
  if (!aiPrompt.value?.trim()) return
  aiGenerating.value = true
  aiGeneratedCode.value = ''
  try {
    // 收集可用变量信息作为上下文
    const contextDesc = []
    const upstream = getUpstreamSteps(selectedStep.value.id)
    for (const step of upstream) {
      if (step.output_key) contextDesc.push(`- context.${step.output_key}（${step.name} 的输出）`)
    }
    for (const v of variables.value) {
      const name = typeof v === 'string' ? v : v.name
      contextDesc.push(`- context.${name}（工作流变量）`)
    }
    const contextInfo = contextDesc.length > 0
      ? `可用的上游变量：\n${contextDesc.join('\n')}`
      : '当前没有上游变量，context 为空对象'

    const prompt = `你是一个 JavaScript 脚本生成助手。请根据以下需求生成代码。\n\n要求：
- 必须定义 function main(context) 函数
- main 函数接收 context 对象，包含上游步骤的输出
- 返回值会作为该步骤的输出
- 只返回代码，不要多余解释

${contextInfo}

用户需求：${aiPrompt.value}`

    const res = await agentApi.simpleCall(prompt)
    // 提取代码块（去除可能的 markdown 代码围栏）
    let code = res.response || ''
    const fenceMatch = code.match(/```(?:javascript|js)?\s*\n?([\s\S]*?)```/)
    if (fenceMatch) code = fenceMatch[1].trim()
    aiGeneratedCode.value = code
  } catch (err) {
    aiGeneratedCode.value = `// 生成失败: ${err.message || '未知错误'}`
  } finally {
    aiGenerating.value = false
  }
}

function applyAiCode() {
  if (!aiGeneratedCode.value || !selectedStep.value) return
  selectedStep.value.code = aiGeneratedCode.value
  markDirty()
  scriptEditorTab.value = 'manual'
}

// 当前展开的变量分组（同一时间只展开一个）
const expandedVarGroup = ref(null)

function toggleVarGroup(label) {
  expandedVarGroup.value = expandedVarGroup.value === label ? null : label
}

function setActiveField(fieldName) {
  activeField.value = fieldName
}

// 将 {{变量名}} 插入到当前焦点字段的光标位置
function insertVariable(varName) {
  if (!selectedStep.value || !activeField.value) return
  const tag = `{{${varName}}}`
  const field = activeField.value
  const step = selectedStep.value

  // 找到对应 DOM 元素并在光标处插入
  const el = document.querySelector(`[data-var-field="${field}"] textarea, [data-var-field="${field}"] input`)
  if (el) {
    const start = el.selectionStart ?? el.value?.length ?? 0
    const end = el.selectionEnd ?? start
    const currentVal = el.value || ''
    const newVal = currentVal.slice(0, start) + tag + currentVal.slice(end)

    // 根据字段名写入对应的 step 属性
    setStepFieldValue(step, field, newVal)
    // 恢复光标位置
    requestAnimationFrame(() => {
      el.focus()
      const pos = start + tag.length
      el.setSelectionRange(pos, pos)
    })
  } else {
    // 无焦点元素时追加到末尾
    const currentVal = getStepFieldValue(step, field) || ''
    setStepFieldValue(step, field, currentVal + tag)
  }
  markDirty()
}

function getStepFieldValue(step, field) {
  const parts = field.split('.')
  let obj = step
  for (const p of parts) {
    obj = obj?.[p]
  }
  return obj
}

function setStepFieldValue(step, field, val) {
  const parts = field.split('.')
  let obj = step
  for (let i = 0; i < parts.length - 1; i++) {
    if (!obj[parts[i]]) obj[parts[i]] = {}
    obj = obj[parts[i]]
  }
  obj[parts[parts.length - 1]] = val
}

const toolParamsText = computed({
  get: () => {
    if (!selectedStep.value?.tool_params) return '{}'
    return JSON.stringify(selectedStep.value.tool_params, null, 2)
  },
  set: (val) => {
    if (selectedStep.value) {
      try {
        selectedStep.value.tool_params = JSON.parse(val)
      } catch {
        // 忽略解析错误
      }
    }
  }
})

const httpHeadersText = computed({
  get: () => {
    const h = selectedStep.value?.headers
    if (!h || (typeof h === 'object' && Object.keys(h).length === 0)) return ''
    return typeof h === 'string' ? h : JSON.stringify(h, null, 2)
  },
  set: (val) => {
    if (selectedStep.value) {
      try {
        selectedStep.value.headers = val ? JSON.parse(val) : {}
      } catch { /* 忽略解析错误 */ }
    }
  }
})

const httpBodyText = computed({
  get: () => {
    const b = selectedStep.value?.body
    if (b === undefined || b === null) return ''
    return typeof b === 'string' ? b : JSON.stringify(b, null, 2)
  },
  set: (val) => {
    if (selectedStep.value) {
      try {
        selectedStep.value.body = val ? JSON.parse(val) : null
      } catch { /* 忽略解析错误 */ }
    }
  }
})

// 将 steps 转换为 Vue Flow 节点和边（仅初始加载时调用）
function syncFlowFromSteps() {
  if (!workflow.value?.definition?.steps) return

  const stepList = workflow.value.definition.steps

  // 迁移旧版条件节点（then_step/else_step）到新版 branches
  stepList.forEach(step => {
    if (step.type === 'condition' && !step.branches) {
      step.branches = []
      if (step.then_step) {
        step.branches.push({ id: 'b1', label: '为真', match: '' })
      }
      if (step.else_step) {
        step.branches.push({ id: 'b2', label: '为假', match: '' })
      }
      // 如果旧数据两个都没配，给一个默认分支
      if (step.branches.length === 0) {
        step.branches.push({ id: 'b1', label: '分支 1', match: '' })
      }
      // 清理旧字段
      delete step.then_step
      delete step.else_step
    }
  })

  // 按 depends_on 拓扑分层：同层并排展示并发，跨层从左到右推进
  // start 固定为最左层（level -1），end 随其依赖自然落到最右
  const stepMap = new Map(stepList.map(s => [s.id, s]))
  const levels = {}
  const getLevel = (stepId, visited = new Set()) => {
    if (levels[stepId] !== undefined) return levels[stepId]
    if (visited.has(stepId)) return 0
    visited.add(stepId)
    const step = stepMap.get(stepId)
    if (step && step.type === 'start') {
      levels[stepId] = -1
      return -1
    }
    if (!step || !step.depends_on || step.depends_on.length === 0) {
      levels[stepId] = 0
      return 0
    }
    const level = Math.max(...step.depends_on.map(depId => getLevel(depId, visited))) + 1
    levels[stepId] = level
    return level
  }
  stepList.forEach(s => getLevel(s.id))

  const columnCount = {}
  const nodes = stepList.map(step => {
    const level = levels[step.id] ?? 0
    const row = columnCount[level] ?? 0
    columnCount[level] = row + 1
    return {
      id: step.id,
      type: 'workflow',
      // 优先使用已保存的位置，否则按拓扑层级布局
      position: step.position || { x: 60 + level * 240, y: 60 + row * 130 },
      deletable: !isBoundaryNode(step.id),
      data: {
        label: step.name || step.id,
        stepType: step.type,
        selected: selectedStepId.value === step.id,
        stepId: step.id,
        // 条件节点传递分支数据给 WorkflowNode 渲染动态 Handle
        ...(step.type === 'condition' && step.branches ? { branches: step.branches } : {})
      }
    }
  })

  const edges = []
  stepList.forEach(step => {
    if (step.depends_on && step.depends_on.length > 0) {
      step.depends_on.forEach(depId => {
        edges.push({
          id: `e-${depId}-${step.id}`,
          source: depId,
          target: step.id,
          type: 'workflow'
        })
      })
    }
  })

  flowElements.value = [...nodes, ...edges]
}

// 将 Vue Flow 节点和边转换回 steps
// 连线即真实 depends_on 数据：start→业务 与 业务→end 的边分别落在
// 业务步骤的 depends_on 与 end 的 depends_on 中，保存后持久化
function syncStepsFromFlow() {
  if (!workflow.value) return

  const nodes = flowNodes.value
  const edges = flowEdges.value

  // 更新步骤列表（位置随拖动写入 step，保存时一并持久化）
  const newSteps = nodes.map(node => {
    const existingStep = steps.value.find(s => s.id === node.id)
    return {
      ...(existingStep || { id: node.id, type: 'llm', name: node.data?.label || node.id }),
      id: node.id,
      type: node.data?.stepType || existingStep?.type || 'llm',
      name: node.data?.label || existingStep?.name || node.id,
      position: { x: node.position?.x ?? 0, y: node.position?.y ?? 0 },
      depends_on: edges
        .filter(e => e.target === node.id)
        .map(e => e.source)
    }
  })

  workflow.value.definition.steps = newSteps
}

// 画布 → steps 单向同步；不允许反向重建 flowElements，
// 否则双向 watch 会无限递归，且会重置用户手动摆放的节点位置
watch(flowElements, () => {
  syncStepsFromFlow()
}, { deep: true })

// 节点点击（start/end 是真实边界步骤，同样打开编辑面板配置输入/输出）
const onNodeClick = (event) => {
  const nodeId = event.node.id
  selectedStepId.value = nodeId
  stepPanelCollapsed.value = false
  expandedVarGroup.value = null
  loopConfigExpanded.value = false
  // 更新选中状态
  flowElements.value.forEach(el => {
    if (!el.source && !el.target) {
      el.data = { ...el.data, selected: el.id === nodeId }
    }
  })
}

// 连线（拒绝自环、重复边，以及流入开始/流出结束的非法方向）
const onConnect = (params) => {
  if (params.source === params.target) return
  if (params.target === START_NODE_ID || params.source === END_NODE_ID) return
  const duplicated = flowEdges.value.some(
    e => e.source === params.source && e.target === params.target
  )
  if (duplicated) return
  // 必须走 addEdges：自动生成 edge id 并更新内部 state，手动 push 数组会因缺 id 被丢弃
  addEdges([{ ...params, type: 'workflow' }])
  markDirty()
}

// 节点位置变化
const onNodesChange = (changes) => {
  changes.forEach(change => {
    if (change.type === 'remove') {
      const nodeId = change.id
      // 同时删除相关边
      flowElements.value = flowElements.value.filter(
        e => (e.source && e.source !== nodeId && e.target !== nodeId) || (!e.source && !e.target && e.id !== nodeId)
      )
      if (selectedStepId.value === nodeId) {
        selectedStepId.value = null
      }
      markDirty()
    }
    // 拖动结束时标记（dragging=false 的是每次拖动的最终一条 change）
    if (change.type === 'position' && change.dragging === false) {
      markDirty()
    }
  })
}

const onEdgesChange = (changes) => {
  changes.forEach(change => {
    if (change.type === 'remove') {
      markDirty()
    }
  })
}

// 拖拽添加节点
const onDragStart = (event, type) => {
  event.dataTransfer.setData('application/vue-flow-node-type', type)
  event.dataTransfer.effectAllowed = 'move'
}

const onDragOver = (event) => {
  event.preventDefault()
  event.dataTransfer.dropEffect = 'move'
}

const onDrop = (event) => {
  event.preventDefault()

  const type = event.dataTransfer.getData('application/vue-flow-node-type')
  if (!type) return

  const position = project({
    x: event.clientX - event.currentTarget.getBoundingClientRect().left,
    y: event.clientY - event.currentTarget.getBoundingClientRect().top
  })

  const id = `step_${Date.now()}`
  const newNode = {
    id,
    type: 'workflow',
    position,
    data: {
      label: `${stepTypes[type]} ${steps.value.length + 1}`,
      stepType: type,
      selected: false,
      stepId: id
    }
  }

  flowElements.value = [...flowElements.value, newNode]

  // 同时添加到 steps，按类型初始化默认字段
  const newStep = {
    id,
    type,
    name: newNode.data.label,
    depends_on: [],
    ...getStepDefaults(type)
  }
  workflow.value.definition.steps.push(newStep)

  selectedStepId.value = id
  markDirty()
}

// 名称编辑同步到画布节点（画布是主编辑入口，表单只做定点回写）
const onNameChange = () => {
  const node = flowElements.value.find(e => e.id === selectedStepId.value && !e.source && !e.target)
  if (node) {
    node.data = { ...node.data, label: selectedStep.value?.name }
  }
  markDirty()
}

// 方法
const goBack = () => {
  if (isDirty.value) {
    if (!confirm('有未保存的更改，确定离开吗？')) return
  }
  router.push('/workflows')
}

const markDirty = () => {
  isDirty.value = true
}

const loadWorkflow = async () => {
  const id = route.params.id
  try {
    const res = await workflowApi.get(id)
    workflow.value = res.data || res
    if (!workflow.value.definition) {
      workflow.value.definition = { steps: [], variables: [], concurrency: 4 }
    }
    if (!workflow.value.definition.steps) {
      workflow.value.definition.steps = []
    }
    if (!workflow.value.definition.variables) {
      workflow.value.definition.variables = []
    }
    // 平台工作流的变量存储在开始节点内，同步到顶层 definition.variables
    if (workflow.value.definition.variables.length === 0) {
      const startStep = workflow.value.definition.steps.find(s => s.type === 'start')
      if (startStep && startStep.variables && startStep.variables.length > 0) {
        workflow.value.definition.variables = JSON.parse(JSON.stringify(startStep.variables))
      }
    }
    // 旧版定义补齐 start/end 边界步骤并迁移连线；变化后提示保存固化
    if (ensureTerminalSteps()) {
      markDirty()
    }
    syncFlowFromSteps()
  } catch (error) {
    console.error('加载工作流失败:', error)
    message.error('加载工作流失败')
  }
}

// 旧版定义没有 start/end 边界步骤：补齐节点并把入口/出口步骤接入。
// 只对完全无边界步骤的旧数据一次性迁移（legacy），之后连线完全由用户管理
function ensureTerminalSteps() {
  const stepList = workflow.value.definition.steps
  const hasStart = stepList.some(s => s.type === 'start')
  const hasEnd = stepList.some(s => s.type === 'end')
  if (hasStart && hasEnd) return false

  let changed = false
  if (!hasStart) {
    stepList.unshift({ id: START_NODE_ID, type: 'start', name: '开始', depends_on: [] })
    changed = true
  }
  if (!hasEnd) {
    stepList.push({ id: END_NODE_ID, type: 'end', name: '结束', depends_on: [] })
    changed = true
  }

  if (!hasStart && !hasEnd) {
    // 入度0业务步骤挂到 start 之后，出度0业务步骤汇入 end
    const businessSteps = stepList.filter(s => s.type !== 'start' && s.type !== 'end')
    const hasSuccessor = new Set()
    businessSteps.forEach(s => (s.depends_on || []).forEach(d => hasSuccessor.add(d)))
    businessSteps.forEach(s => {
      if (!s.depends_on || s.depends_on.length === 0) {
        s.depends_on = [START_NODE_ID]
      }
    })
    stepList.find(s => s.type === 'end').depends_on = businessSteps
      .filter(s => !hasSuccessor.has(s.id))
      .map(s => s.id)
  }
  return changed
}

const saveWorkflow = async () => {
  if (!workflow.value) return
  // 保存前同步变量到开始节点（平台工作流变量存储在开始节点内）
  syncVariablesToStartNode()
  saving.value = true
  try {
    await workflowApi.update(workflow.value.id, {
      name: workflow.value.name,
      definition: workflow.value.definition
    })
    message.success('保存成功')
    isDirty.value = false
  } catch (error) {
    console.error('保存失败:', error)
    message.error('保存失败')
  } finally {
    saving.value = false
  }
}

const addVariable = () => {
  workflow.value.definition.variables.push({ name: '', label: '', default: '' })
  markDirty()
}

const removeVariable = (idx) => {
  workflow.value.definition.variables.splice(idx, 1)
  markDirty()
}

// 将 definition.variables 同步回开始节点（平台工作流变量存储在开始节点内）
const syncVariablesToStartNode = () => {
  const startStep = workflow.value.definition.steps.find(s => s.type === 'start')
  if (startStep) {
    startStep.variables = JSON.parse(JSON.stringify(workflow.value.definition.variables || []))
  }
}

const addGlobalVariable = () => {
  if (!workflow.value.definition.global_variables) {
    workflow.value.definition.global_variables = []
  }
  workflow.value.definition.global_variables.push({ name: '', label: '', default: '' })
  markDirty()
}

const removeGlobalVariable = (idx) => {
  workflow.value.definition.global_variables.splice(idx, 1)
  markDirty()
}

const confirmRemoveStep = (stepId) => {
  if (isBoundaryNode(stepId)) return
  Modal.confirm({
    title: '确认删除',
    content: '确定要删除这个步骤吗？删除后不可恢复。',
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    onOk: () => removeStep(stepId),
  })
}

const removeStep = (stepId) => {
  // start/end 是流程边界步骤，不允许删除
  if (isBoundaryNode(stepId)) return

  // 从 flow 中删除节点和相关边
  flowElements.value = flowElements.value.filter(
    e => (e.source && e.source !== stepId && e.target !== stepId) || (!e.source && !e.target && e.id !== stepId)
  )

  // 从 steps 中删除
  const idx = steps.value.findIndex(s => s.id === stepId)
  if (idx >= 0) {
    workflow.value.definition.steps.splice(idx, 1)
  }

  if (selectedStepId.value === stepId) {
    selectedStepId.value = null
  }
  markDirty()
}

const getMiniMapColor = (node) => {
  const colors = {
    start: '#22c55e',
    llm: '#14b8a6',
    tool: '#f59e0b',
    http: '#3b82f6',
    condition: '#ec4899',
    approval: '#8b5cf6',
    script: '#6b7280',
    output: '#10b981',
    end: '#9ca3af'
  }
  return colors[node.data?.stepType] || '#14b8a6'
}

const handleRunClick = () => {
  if (isDirty.value) {
    Modal.confirm({
      title: '工作流未保存',
      content: '检测到工作流有未保存的修改，是否先保存再运行？',
      okText: '保存并运行',
      cancelText: '直接运行',
      async onOk() {
        await saveWorkflow()
        showRunModal.value = true
      },
      onCancel() {
        showRunModal.value = true
      },
    })
  } else {
    showRunModal.value = true
  }
}

const handleRun = async () => {
  running.value = true
  try {
    const res = await workflowApi.run(workflow.value.id, runInputs.value)
    const runData = res.data || res
    showRunModal.value = false
    // 打开结果弹窗并开始轮询
    showRunResult.value = true
    runResultLoading.value = true
    runResultData.value = null
    pollRunResult(runData.id)
  } catch (error) {
    console.error('运行失败:', error)
    // 409 = 已有正在运行的工作流，给出友好提示
    if (error?.response?.status === 409) {
      message.warning(error?.response?.data?.detail || '工作流正在运行中，请等待完成后再次提交')
    } else {
      message.error('运行失败')
    }
  } finally {
    running.value = false
  }
}

const pollRunResult = async (runId) => {
  if (runPollTimer) clearInterval(runPollTimer)

  // 立即执行一次查询，避免首次显示全部"等待中"
  const fetchRun = async () => {
    try {
      const res = await workflowApi.getRun(runId)
      const data = res.data || res
      runResultData.value = data
      if (runResultLoading.value) {
        runResultLoading.value = false
      }
      if (data.status === 'running') {
        scrollToActiveStep()
      }
      if (data.status === 'completed' || data.status === 'failed') {
        clearInterval(runPollTimer)
        runPollTimer = null
      }
    } catch (e) {
      console.error('查询运行结果失败:', e)
      clearInterval(runPollTimer)
      runPollTimer = null
      runResultLoading.value = false
    }
  }

  // 立即查询一次
  await fetchRun()
  // 然后每 2 秒轮询
  runPollTimer = setInterval(fetchRun, 2000)
}

/** 关闭运行结果弹窗时清理轮询定时器（不影响后端异步执行） */
function onRunResultClose() {
  if (runPollTimer) {
    clearInterval(runPollTimer)
    runPollTimer = null
  }
}

/** 强制终止卡住的工作流运行 */
async function handleCancelRun(runId) {
  Modal.confirm({
    title: '确认强制关闭',
    content: '确定要强制终止这个工作流运行吗？未完成的步骤将被标记为失败。',
    okText: '确认关闭',
    okType: 'danger',
    cancelText: '取消',
    onOk: async () => {
      cancellingRun.value = true
      try {
        await workflowApi.cancelRun(runId)
        message.success('工作流运行已强制关闭')
        // 停止轮询
        if (runPollTimer) {
          clearInterval(runPollTimer)
          runPollTimer = null
        }
        // 刷新运行详情
        if (runResultData.value && runResultData.value.id === runId) {
          const res = await workflowApi.getRun(runId)
          runResultData.value = res.data || res
        }
        // 刷新运行历史
        if (showRunHistory.value) {
          const res = await workflowApi.listRuns(workflow.value.id)
          runHistoryList.value = (res.data || res) || []
        }
        // 重置运行状态
        running.value = false
      } catch (e) {
        console.error('强制关闭失败:', e)
        if (e?.response?.status === 409) {
          message.warning(e?.response?.data?.detail || '运行已终结，无法取消')
        } else {
          message.error('强制关闭失败')
        }
      } finally {
        cancellingRun.value = false
      }
    },
  })
}

function formatRunOutput(val) {
  if (val === null || val === undefined) return ''
  if (typeof val === 'string') return val
  return JSON.stringify(val, null, 2)
}

const openRunHistory = async () => {
  showRunHistory.value = true
  runHistoryLoading.value = true
  try {
    const res = await workflowApi.listRuns(workflow.value.id)
    runHistoryList.value = (res.data || res) || []
  } catch (e) {
    console.error('加载运行历史失败:', e)
    message.error('加载运行历史失败')
  } finally {
    runHistoryLoading.value = false
  }
}

const viewRunDetail = async (run) => {
  showRunHistory.value = false
  showRunResult.value = true
  runResultLoading.value = true
  runResultData.value = null
  try {
    const res = await workflowApi.getRun(run.id)
    runResultData.value = res.data || res
    runResultLoading.value = false
  } catch (e) {
    console.error('加载运行详情失败:', e)
    message.error('加载运行详情失败')
    runResultLoading.value = false
  }
}

function formatRunTime(timeStr) {
  if (!timeStr) return ''
  const d = new Date(timeStr)
  if (isNaN(d.getTime())) return timeStr
  return d.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

onMounted(async () => {
  await loadWorkflow()
  loadAgents()
  // 支持从定时任务历史跳转查看运行详情：/workflows/:id?run_id=xxx
  const runId = route.query.run_id
  if (runId) {
    showRunResult.value = true
    runResultLoading.value = true
    runResultData.value = null
    try {
      const res = await workflowApi.getRun(runId)
      runResultData.value = res.data || res
      runResultLoading.value = false
    } catch (e) {
      console.error('加载运行详情失败:', e)
      message.error('加载运行详情失败')
      runResultLoading.value = false
    }
  }
})

const loadAgents = async () => {
  try {
    const res = await agentApi.getAgents()
    const list = res.agents || []
    agentOptions.value = list.map(a => ({
      slug: a.slug,
      name: a.name || a.slug
    }))
  } catch (e) {
    console.error('加载 Agent 列表失败:', e)
  }
}

const agentFilterOption = (input, option) => {
  const keyword = input.toLowerCase()
  return (option?.label || '').toLowerCase().includes(keyword)
}
</script>

<style scoped>
.workflow-editor {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--gray-0);
}

.editor-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--gray-150);
  background: var(--gray-25);
  flex-shrink: 0;
}

.toolbar-left,
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.toolbar-left :deep(.ant-btn),
.toolbar-right :deep(.ant-btn) {
  display: inline-flex;
  align-items: center;
  vertical-align: middle;
}

.toolbar-left :deep(.ant-btn-icon),
.toolbar-right :deep(.ant-btn-icon) {
  display: inline-flex;
  align-items: center;
  margin-right: 6px;
  vertical-align: middle;
}

.workflow-name-input {
  width: 240px;
  font-size: 16px;
  font-weight: 600;
}

.editor-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
  position: relative;
}

/* 画布占满剩余空间 */
.flow-canvas {
  flex: 1;
  position: relative;
  overflow: hidden;
  background: #fafbfc;
  min-height: 0;
}

.flow-canvas :deep(.vue-flow) {
  width: 100%;
  height: 100%;
}

.canvas-empty-hint {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  text-align: center;
  color: var(--gray-400);
  pointer-events: none;
  z-index: 1;
}

.canvas-empty-hint p {
  margin-top: 12px;
  font-size: 14px;
}

/* 浮动：全局设置按钮 */
.floating-settings-btn {
  position: absolute;
  top: 12px;
  left: 12px;
  z-index: 20;
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #fff;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  cursor: pointer;
  color: var(--gray-600);
  transition: all 0.15s;
  box-shadow: 0 1px 4px var(--shadow-1);
}

.floating-settings-btn:hover {
  color: var(--main-600);
  border-color: var(--main-400);
  box-shadow: 0 2px 8px var(--shadow-1);
}

/* 浮动：全局设置面板 */
.floating-settings-panel {
  position: absolute;
  top: 56px;
  left: 12px;
  z-index: 30;
  width: 240px;
  background: #fff;
  border: 1px solid var(--gray-150);
  border-radius: 10px;
  box-shadow: 0 4px 16px var(--shadow-2);
  overflow: hidden;
}

.settings-content {
  padding: 12px 16px 16px;
}

.settings-row {
  margin-bottom: 12px;
}

.settings-label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: var(--gray-700);
  margin-bottom: 6px;
}

/* 浮动：步骤编辑抽屉 */
.step-drawer {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  z-index: 10;
  width: 380px;
  display: flex;
  flex-direction: column;
  background: #fff;
  border-left: 1px solid var(--gray-150);
  box-shadow: -2px 0 12px var(--shadow-1);
  transition: width 0.2s ease;
  overflow: hidden;
}

.step-drawer.collapsed {
  width: 44px;
}

.step-drawer.collapsed .step-form {
  display: none;
}

.step-drawer.collapsed .panel-header span {
  display: none;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--gray-150);
  font-size: 13px;
  font-weight: 600;
  color: var(--gray-700);
  flex-shrink: 0;
}

.panel-header-left {
  display: flex;
  align-items: center;
  gap: 4px;
}

.panel-header-left span {
  display: inline;
}

.panel-header-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.step-form {
  flex: 1;
  overflow: auto;
  padding: 16px;
}

.step-form :deep(.ant-form-item) {
  margin-bottom: 14px;
}

.step-form :deep(.ant-form-item-label > label) {
  font-size: 13px;
  font-weight: 500;
}

.step-form :deep(.ant-divider) {
  margin: 16px 0 12px;
  font-size: 12px;
  color: var(--gray-400);
}

.node-type-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  font-size: 14px;
  font-weight: 500;
  color: var(--gray-700);
  background: var(--gray-100);
  border-radius: 6px;
}


/* 可用变量面板 */
.var-panel {
  background: var(--gray-25);
  border: 1px solid var(--gray-150);
  border-radius: 6px;
  padding: 8px 10px;
  margin-bottom: 12px;
}

.var-panel-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--gray-500);
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.var-group {
  margin-bottom: 2px;
}

.var-group-header {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 6px;
  border-radius: 4px;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s;
  font-size: 11px;
}

.var-group-header:hover {
  background: rgba(0, 0, 0, 0.04);
}

.var-group-expanded {
  background: rgba(20, 184, 166, 0.06);
}

.var-group-arrow {
  font-size: 10px;
  color: var(--gray-400);
  width: 12px;
  flex-shrink: 0;
  text-align: center;
}

.var-group-label {
  font-size: 11px;
  color: var(--gray-600);
  font-weight: 500;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.var-group-count {
  font-size: 10px;
  color: var(--gray-400);
  background: var(--gray-100);
  border-radius: 8px;
  padding: 0 5px;
  line-height: 16px;
  flex-shrink: 0;
}

.var-group-body {
  padding: 2px 0 4px 18px;
}

.var-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  margin: 0 4px 4px 0;
  background: #fff;
  border: 1px solid var(--gray-200);
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s;
  user-select: none;
}

.var-tag:hover {
  border-color: #14b8a6;
  color: #0d9488;
  background: #f0fdfa;
}

.var-tag-name {
  font-weight: 600;
  font-family: var(--font-mono, monospace);
}

.var-tag-label {
  color: var(--gray-600);
  font-size: 0.9em;
  margin-right: 4px;
}

.var-tag-desc {
  color: var(--gray-400);
  font-size: 10px;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 条件分支表单行 */
.condition-branch-row {
  border: 1px solid var(--gray-150);
  border-radius: 6px;
  padding: 8px 10px;
  margin-bottom: 8px;
  background: var(--gray-25);
}

.condition-branch-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}

.condition-branch-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.condition-branch-name-input {
  flex: 1;
  font-size: 12px;
}

.condition-branch-match-input {
  font-size: 12px;
}

.condition-add-branch-btn {
  margin-top: 4px;
  font-size: 12px;
}

/* 底部节点工具栏 */
.node-palette-bar {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 8px;
  padding: 8px 16px;
  background: var(--gray-25);
  border-top: 1px solid var(--gray-150);
  flex-shrink: 0;
  overflow-x: auto;
}

.palette-bar-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: #fff;
  border: 1px solid var(--gray-150);
  border-radius: 6px;
  cursor: grab;
  transition: all 0.15s;
  user-select: none;
  white-space: nowrap;
  flex-shrink: 0;
}

.palette-bar-item:hover {
  border-color: var(--main-400);
  box-shadow: 0 2px 6px var(--shadow-1);
  transform: translateY(-1px);
}

.palette-bar-item:active {
  cursor: grabbing;
}

.palette-bar-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 5px;
  background: var(--main-50);
  color: var(--main-600);
  flex-shrink: 0;
}

.palette-bar-label {
  font-size: 12px;
  color: var(--gray-700);
}

/* Start 节点面板中的变量行 */
.start-variable-item {
  display: flex;
  gap: 4px;
  margin-bottom: 6px;
  align-items: center;
}

.global-var-item {
  display: flex;
  gap: 4px;
  margin-bottom: 6px;
  align-items: center;
}

.empty-variables {
  text-align: center;
  color: var(--gray-400);
  font-size: 12px;
  padding: 16px 0;
}

.panel-hint {
  font-size: 11px;
  color: var(--gray-400);
  line-height: 1.5;
}

/* 循环配置区域 */
.loop-config-section {
  margin-top: 8px;
}

.loop-config-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 0;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  color: var(--gray-600);
  user-select: none;

  &:hover {
    color: var(--gray-900);
  }
}

.loop-config-arrow {
  font-size: 12px;
  width: 14px;
  text-align: center;
}

.loop-config-badge {
  display: inline-flex;
  align-items: center;
  height: 18px;
  padding: 0 6px;
  margin-left: 4px;
  border-radius: 9px;
  background: var(--main-50);
  color: var(--main-600);
  font-size: 11px;
  font-weight: 500;
}

.loop-config-badge--warn {
  background: var(--color-warning-50);
  color: var(--color-warning-700);
}

.loop-config-help-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  margin-left: auto;
  border-radius: 50%;
  color: var(--gray-400);
  cursor: pointer;
  transition: all 0.2s;

  &:hover {
    color: var(--main-600);
    background: var(--main-50);
  }
}

.loop-config-intro {
  padding: 8px 12px;
  margin-bottom: 12px;
  background: var(--gray-50, #fafafa);
  border-radius: 6px;
  border: 1px solid var(--gray-100, #f0f0f0);

  p {
    margin: 0;
    font-size: 12px;
    line-height: 1.6;
    color: var(--gray-500);
  }
}

.loop-config-body {
  padding: 8px 0 4px;
}

/* 循环配置指南弹窗 */
.loop-help-modal {
  .ant-modal-body {
    padding: 16px 24px 24px;
  }
}

.loop-help-content {
  font-size: 13px;
  line-height: 1.8;
  color: var(--gray-700);

  h4 {
    margin: 16px 0 8px;
    font-size: 14px;
    font-weight: 600;
    color: var(--gray-800);

    &:first-child {
      margin-top: 0;
    }
  }

  p {
    margin: 4px 0;
  }

  ul {
    margin: 4px 0 8px;
    padding-left: 20px;
  }

  li {
    margin: 2px 0;
  }

  code {
    padding: 1px 5px;
    background: var(--gray-100, #f5f5f5);
    border-radius: 3px;
    font-family: 'Cascadia Code', 'Fira Code', monospace;
    font-size: 12px;
    color: var(--main-700);
  }

  .loop-help-example {
    margin: 8px 0 12px;
    padding: 10px 14px;
    background: var(--gray-50, #fafafa);
    border-radius: 6px;
    border: 1px solid var(--gray-100, #f0f0f0);
    font-size: 12px;
    line-height: 1.7;

    .loop-help-example-title {
      font-weight: 600;
      color: var(--gray-700);
      margin-bottom: 4px;
    }
  }
}

/* 脚本代码编辑区 */
.code-editor :deep(textarea) {
  font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.5;
  tab-size: 4;
}

/* CodeMirror 容器样式适配 */
:deep(.cm-editor) {
  border: 1px solid var(--gray-200);
  border-radius: 6px;
  outline: none;
}

:deep(.cm-editor.cm-focused) {
  border-color: var(--primary-6);
}

/* 脚本测试结果面板 */
.script-test-result {
  border: 1px solid var(--gray-200);
  border-radius: 6px;
  overflow: hidden;
  margin-top: -4px;
}

.script-test-result-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 8px;
  background: var(--gray-50);
  border-bottom: 1px solid var(--gray-150);
  font-size: 11px;
  font-weight: 600;
  color: var(--gray-600);
}

.script-test-output {
  margin: 0;
  padding: 8px 10px;
  font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
  font-size: 12px;
  line-height: 1.5;
  color: var(--gray-700);
  background: var(--gray-25);
  max-height: 200px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

.script-test-error {
  color: var(--danger-6);
  background: var(--danger-50);
}

/* 脚本编辑器 Tab */
.script-editor-tabs :deep(.ant-tabs-nav) {
  margin-bottom: 8px;
}

.script-editor-tabs :deep(.ant-tabs-tab) {
  font-size: 12px;
  padding: 4px 12px;
}

/* AI 代码生成面板 */
.ai-code-gen-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.ai-code-gen-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.ai-gen-hint {
  font-size: 11px;
  color: var(--primary-6);
  animation: pulse 1.5s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.ai-generated-preview {
  border: 1px solid var(--gray-200);
  border-radius: 6px;
  overflow: hidden;
}

.ai-preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 8px;
  background: var(--gray-50);
  border-bottom: 1px solid var(--gray-150);
  font-size: 11px;
  font-weight: 600;
  color: var(--gray-600);
}

.ai-preview-header div {
  display: flex;
  gap: 4px;
}

.ai-preview-code {
  margin: 0;
  padding: 8px 10px;
  font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
  font-size: 12px;
  line-height: 1.5;
  color: var(--gray-700);
  background: var(--gray-25);
  max-height: 240px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

/* 运行历史弹窗 */
.run-history-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 480px;
  overflow-y: auto;
}

.run-history-item {
  padding: 10px 14px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s;
}

.run-history-item:hover {
  background: var(--gray-50);
}

.run-history-item-main {
  display: flex;
  align-items: center;
  gap: 10px;
}

.run-history-time {
  font-size: 13px;
  color: var(--gray-500);
}

.run-history-error {
  margin-top: 6px;
  font-size: 12px;
  color: var(--danger-500, #ef4444);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 运行结果弹窗 */
.run-result-status {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}

.run-result-progress {
  font-size: 12px;
  color: var(--gray-500);
}

.run-result-error-msg {
  font-size: 12px;
  color: var(--danger-500, #ef4444);
}

.run-result-context-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--gray-600);
  margin-bottom: 10px;
}

.run-result-steps {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.run-result-step {
  border: 1px solid var(--gray-150);
  border-radius: 6px;
  padding: 8px 12px;
  background: var(--gray-25);
  transition: all 0.3s ease;
}

.run-result-step-active {
  border-color: var(--primary-300, #91caff);
  background: var(--primary-25, #f0f5ff);
  box-shadow: 0 0 0 2px var(--primary-100, #e6f4ff);
}

.run-result-step-done {
  border-color: var(--success-200, #b7eb8f);
  background: var(--success-25, #f6ffed);
}

.run-result-step-failed {
  border-color: var(--danger-200, #ffa39e);
  background: var(--danger-25, #fff2f0);
}

.run-result-step-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.run-result-step-icon {
  display: flex;
  align-items: center;
  font-size: 16px;
}

.run-result-step-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--gray-700);
}

.run-result-step-output pre {
  margin: 0;
  padding: 8px 10px;
  font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
  font-size: 12px;
  line-height: 1.5;
  color: var(--gray-700);
  background: #fff;
  border-radius: 4px;
  max-height: 200px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

.run-result-step-error {
  font-size: 12px;
  color: var(--danger-500, #ef4444);
  padding: 4px 0;
}
</style>

<style>
/* 运行结果弹窗 - 非 scoped 样式，因为 modal wrapper 渲染在 body 下 */
.run-result-modal.ant-modal-wrap {
  overflow: hidden !important;
}

.run-result-modal .ant-modal {
  top: 5vh !important;
  margin: 0 auto !important;
}
</style>
