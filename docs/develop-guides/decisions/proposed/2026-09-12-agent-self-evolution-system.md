# Agent 自进化体系：对话后经验沉淀与技能自动演化

状态：proposed
类型：architecture
Owner：`backend/package/yuxi/agents/`（Agent 运行时）、`backend/package/yuxi/services/`（领域服务）

## 问题

Agent 在大量对话中积累了可复用的工作流经验、用户偏好纠正和调试路径，但这些经验仅存在于对话历史中，下次会话无法自动复用。用户反复纠正同类错误、重复描述偏好，Agent 无法从自身执行历史中持续改进。

当前 Yuxi 已有外部安装的 `self-improving-agent` 技能（基于多重记忆架构），但它需要显式调用，不具备自动触发、质量守门和定期整理能力。

参考 Hermes Agent 的自进化体系（`background_review.py` + `curator.py`），其核心设计是：
- **每轮对话后**自动在后台 fork 一个回顾 Agent，提取经验写入 Memory 和 Skill
- **严格的经验质量规范**：过滤临时错误、环境依赖失败、未验证结论
- **后台策展人**定期合并重复技能、归档过期经验、防止技能膨胀

## 提案

分三个阶段在 Yuxi Agent 运行时中内建自进化能力，复用现有 Memory 系统和 Skill 框架。

### 阶段一：对话后自动回顾（Background Review）

在 `AgentRun` 进入终态后，通过 ARQ 投递一个轻量回顾任务：

1. **触发时机**：`AgentRun` 状态变为 `completed` / `failed` 后，由 `run_worker` 在终态处理中投递 ARQ 回顾任务
2. **回顾内容**：取该 Run 的完整消息序列（含工具调用和结果），构造回顾 prompt 发送给 LLM
3. **双维度提取**：
   - **用户画像维度**：偏好、风格要求、行为期望 → 写入用户 Memory
   - **做事方法维度**：工作流纠正、新技术、调试路径 → 写入 Agent 级经验记录
4. **并发安全**：回顾任务为低优先级 ARQ 任务，不阻塞主对话；用户发送新消息时不取消回顾（与 Hermes 不同，Yuxi 通过 ARQ 队列天然解耦）

语义 Owner：
- 触发逻辑：`backend/package/yuxi/services/run_worker.py`
- 回顾 prompt 构造与 LLM 调用：新增 `backend/package/yuxi/services/experience_review.py`
- 写入目标：现有 Memory 存储（DeepAgents 文件后端）+ 新增经验记录表

### 阶段二：经验质量守门（Quality Gate）

在回顾 LLM 的 prompt 中内建过滤规则，参考 Hermes 的 `_LESSON_LAYER_BLOCK` 和 `_DO_NOT_CAPTURE_BLOCK`：

**应该沉淀的信号**：
- 用户纠正了 Agent 的风格、格式、详细程度或工作流顺序
- 非平凡的技术方案、修复路径或工具使用模式
- Agent 加载的 Skill 被发现过时、遗漏步骤或错误

**不应沉淀的过滤规则**：
- 环境依赖的失败（缺依赖、未配置凭证、命令未安装）——用户可自行修复
- 对工具/功能的否定判断（"X 工具不能用"）——会在环境变化后变成错误约束
- 会话内已自行解决的临时错误——重试成功则教训是重试模式本身
- 一次性任务叙事——不构成可复用的工作流类别
- 未验证的结论——会话结束时仍未找到可行方案时，不将失败尝试包装为最佳实践

**经验格式规范**：
- 程序优先：步骤按执行顺序排列，附带具体命令和决策点
- 教训 = 可泛化规则 + 一句 WHY（机制），不是事件叙事
- 去重：同一条教训出现多次合并为一条规则
- 不重复环境已有的知识（AGENTS.md、工具 schema 等）
- 不带 PR 号、日期、事件引用——规则必须脱离事件独立成立

语义 Owner：
- 质量守门逻辑嵌入回顾 prompt，由 LLM 自行判断
- 经验记录 Schema：`backend/package/yuxi/repositories/` 新增经验数据访问

### 阶段三：定期经验整理（Curator）

通过 ARQ 定时任务（复用现有 `scheduled-agents` 基础设施或独立 cron），周期性执行经验库的结构维护：

1. **去重合并**：检测语义重复的经验记录，合并为更完整的单一规则
2. **过期归档**：超过 N 天未被引用的经验标记为 stale，再超过 M 天后归档
3. **冲突检测**：发现两条经验对同一场景给出矛盾建议时，标记待人工审阅
4. **技能关联**：将高频被引用的经验自动关联到对应 Skill，建议 Skill 更新

语义 Owner：
- 定时触发：ARQ 定时任务或独立 cron
- 整理逻辑：新增 `backend/package/yuxi/services/experience_curator.py`
- 持久化：经验记录表 + 状态字段（active / stale / archived）

## 替代方案

### 方案 A：仅依赖外部 Skill（当前方案）

继续使用外部安装的 `self-improving-agent` 技能，不做内建。
- 优点：零开发成本，立即可用
- 缺点：需要显式调用，无法自动触发；无质量守门，可能沉淀低质量经验；无定期整理，经验库会膨胀

### 方案 B：完全对齐 Hermes 的后台线程模型

在 Agent 进程内用守护线程 fork 回顾 Agent，而非通过 ARQ。
- 优点：与 Hermes 设计一致，prefix cache 命中率高
- 缺点：Yuxi 的 Agent 运行在 ARQ worker 中，进程模型不同；守护线程与 FastAPI 事件循环的兼容复杂度高；崩溃恢复不如 ARQ 可靠
- 结论：不采用。Yuxi 已有成熟的 ARQ 任务队列，利用它做异步回顾更自然

### 方案 C：仅在用户显式触发时回顾

提供一个 `/review` 斜杠命令，让用户手动触发经验提取。
- 优点：实现简单，用户完全控制
- 缺点：依赖用户主动性，大多数时候不会触发；失去"每轮自动学习"的核心价值
- 结论：可作为阶段一的补充，但不替代自动触发

## 验收标准

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| AgentRun 完成后自动投递回顾 ARQ 任务 | 任务未投递或投递到错误队列 | `run_worker.py` | 运行 Agent 对话后检查 ARQ 队列 | AgentRun 失败时不应投递回顾任务 | 未实现 |
| 回顾任务提取的用户偏好写入 Memory | 写入失败或写入错误用户 | `experience_review.py` | 检查 Memory 存储中新增的记录 | 对话中无用户偏好信号时不应产生 Memory 写入 | 未实现 |
| 回顾任务提取的工作经验写入经验记录 | 写入失败或格式不符规范 | `experience_review.py` | 检查经验记录表中的新增条目 | 对话中无技术经验信号时不应产生记录 | 未实现 |
| 质量守门过滤掉环境依赖失败 | 临时错误被错误沉淀 | 回顾 prompt | 构造含环境失败的对话，验证不产生经验记录 | —— | 未实现 |
| 质量守门过滤掉未验证结论 | 失败尝试被包装为最佳实践 | 回顾 prompt | 构造未解决问题的对话，验证不产生"推荐方案" | —— | 未实现 |
| 定期整理合并语义重复的经验 | 重复经验未被合并 | `experience_curator.py` | 手动插入两条语义重复记录，运行整理后验证合并 | 两条内容不同但主题相近的记录不应被强制合并 | 未实现 |
| 定期整理归档过期经验 | 过期经验未被标记 | `experience_curator.py` | 插入超过 N 天未被引用的记录，验证标记为 stale | 最近被引用的记录不应被标记 | 未实现 |

## 风险

1. **LLM 成本**：每轮对话后额外一次 LLM 调用，高频使用场景下成本可观。缓解：回顾任务使用低成本模型（如 `gpt-4o-mini`），且仅在对话超过一定轮次时触发。
2. **经验质量**：LLM 可能错误判断什么值得沉淀。缓解：阶段二的质量守门 prompt 经过充分测试；提供前端界面让用户审阅和删除低质量经验。
3. **隐私安全**：回顾过程可能提取敏感信息。缓解：遵循现有 Memory 的权限边界，经验记录按用户和 Agent 隔离，不跨租户共享。
4. **经验膨胀**：长期运行后经验记录过多，影响检索质量。缓解：阶段三的定期整理 + 过期归档机制。
5. **与现有 Skill 的关系**：经验记录和 Skill 的边界需要明确。初步设计：经验记录是原始素材，Skill 是经过验证的工作流指令；阶段三可自动建议将高频经验沉淀到 Skill。

## 参考资料

- Hermes Agent `background_review.py`：每轮对话后 fork 回顾 Agent 的完整实现
- Hermes Agent `curator.py`：后台技能维护与整合机制
- Hermes Agent `_LESSON_LAYER_BLOCK`：经验质量规范（什么才算好的经验）
- Hermes Agent `_DO_NOT_CAPTURE_BLOCK`：经验过滤规范（什么不该沉淀）
- Yuxi 现有 Memory 系统：DeepAgents 文件后端
- Yuxi 现有 ARQ 任务队列：`services/arq_worker.py`
