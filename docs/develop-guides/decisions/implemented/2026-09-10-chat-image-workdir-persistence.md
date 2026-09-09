# 聊天内嵌图片落盘到 Project Workdir

状态：implemented
类型：bug-fix
Owner：backend/package/yuxi/services/chat_service.py

## 问题

用户在对话中直接发送图片（base64 内嵌于消息 `image_url` block，持久化在 `messages.image_content`）后：

1. 图片从未写入 Project Workdir——agent 文件工具（ls/glob/find）在 `{workdir}/uploads/` 找不到文件（真实案例：对话 15 抠图任务，tool 报 `path_not_found`，agent 全盘搜索无果）。
2. 个人空间 `projects/<workdir>/uploads/` 也不可见，用户认为文件丢失。

对比之下，走附件按钮上传的文件经 tmp/confirm 链路由 `_store_attachment` 写入 `uploads/`，两条链路行为不一致。而系统 prompt 明确告诉 agent "`{workdir}/uploads/` 是用户上传文件的目录"，承诺与实现断裂。

## 决策

- 在唯一执行链路 `stream_agent_chat`（ARQ worker 调用）中，消息图片经 `resolve_authorized_conversation_workdir` 授权解析后由 `store_chat_image_attachment` 落盘到 `uploads/image-<request_id前12位>.<扩展名>`。
- 落盘后的图片记录追加进 `_with_attachment_context` 注入的本轮模型输入，agent 直接获得可读路径，无需猜测。
- 失败降级：base64 非法或写入异常仅记录 warning，不阻断对话（模型多模态输入仍含原图）。
- 幂等：文件名以 request_id 为前缀，同一请求重放覆盖同一文件，不产生重复副本。
- 不写入 `request_attachments` 持久化元数据，避免前端消息 UI 重复渲染同一图片。

## 替代方案

1. 只靠 prompt 让 agent 用多模态输入处理图片、不提供文件路径——被否：文件类工具（抠图/编辑/另存）无法访问二进制内容，即本次缺陷。
2. 落盘到沙盒 /tmp——被否：生命周期与 Project 脱钩，用户在个人空间不可见、不可复用。
3. 改造前端把聊天图片全部改走 tmp/confirm 附件链路——被否：改动面大，且粘贴截图等交互路径仍会内嵌 base64。

## 后果

- 聊天图片与附件上传文件在 Workdir 内行为一致：agent 可读、个人空间可见、随 Project 生命周期管理。
- 多图消息仅第一张被提取为 `image_content` 并落盘（与现有 `input_message_service` 提取逻辑一致，未扩大）。
- 图片重命名为 `image-<request_id>` 格式，不保留原始文件名（内嵌消息本身不携带文件名）。

## 验证

- `test/unit/test_tmp_attachment_service.py` 新增 3 用例：写入成功（路径与字节一致）、非法 base64 返回 None、写盘失败降级返回 None。
- `test_chat_service_langfuse_stream.py`（21）、`test_run_worker.py`、`test_chat_stream_interrupt.py`（共 73）全部通过，无回归。
- API/worker 重启后 `/api/system/ready` 200。
