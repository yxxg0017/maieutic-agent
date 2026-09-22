# 知识激发智能体桌面端实现说明

> 面向对象：Coding Agent / 实现者  
> 关联规格：`知识激发智能体_实现规格.md`  
> 目标平台：macOS（Apple Silicon 优先）与 Windows 11  
> 选定方案：Tauri v2 + React + assistant-ui + Python/LangGraph sidecar

## 1. 实现目标

构建一个本地优先的跨平台桌面应用，通过“任务框定—资料获取—候选发散—反例批判—综合—学习检查”提高模型回答的信息价值。

桌面端不是普通聊天壳。MVP 必须呈现以下领域信息：

- 当前任务目标、深度模式和价值标准；
- 回答使用的资料及来源等级；
- 实质不同的候选解释或方案；
- 每个候选的依据、假设、风险和验证方法；
- 最终结论、未知项和下一步；
- LangGraph interrupt、恢复及会话历史。

不把“回答更长”作为成功标准。实现和评测以是否增加可靠、非冗余、能改变理解或行动的信息为准。

## 2. 技术选型

### 2.1 固定技术栈

| 层 | 方案 | 用途 |
|---|---|---|
| 桌面壳 | Tauri v2 | 窗口、权限、sidecar 生命周期、安装与更新 |
| 前端 | React + TypeScript + Vite | 产品界面 |
| 对话组件 | assistant-ui | 消息流、工具状态、附件、线程和自定义消息组件 |
| 状态请求 | TanStack Query | 非流式服务状态与缓存 |
| 本地 UI 状态 | Zustand | 面板、选择、草稿等短生命周期状态 |
| 后端 | Python 3.11 + FastAPI | 本地 API、SSE、文件导入与健康检查 |
| 工作流 | LangGraph | Agent 状态图、中断、checkpoint 与恢复 |
| 数据 | SQLite | 会话、来源、候选、Claim、checkpoint 元数据 |
| 数值计算 | NumPy | EIG、归一化和确定性评分聚合 |

依赖必须锁定精确版本。实施时先查询并选择当时稳定版本，将版本写入锁文件；不要从本文猜测版本号，也不要使用 `*`、`latest` 或无上界范围。

### 2.2 不采用完整聊天产品 fork

不直接 fork Open WebUI、AnythingLLM、Cherry Studio 或 LibreChat 作为业务基座。原因：它们已有独立的 Agent、RAG、会话和账户模型，替换为 LangGraph 会产生双重运行时。可参考它们的附件、引用、模型设置与桌面交互，但不得复制许可证不兼容的代码或素材。

## 3. 总体架构

```text
┌──────────────────── Tauri Desktop ────────────────────┐
│                                                       │
│  React + assistant-ui                                 │
│  ├── Conversation                                     │
│  ├── Source Inspector                                 │
│  ├── Candidate Workspace                              │
│  ├── Challenge / Learning Check                       │
│  └── Session / Settings                               │
│           │                                           │
│           │ HTTP + SSE（仅 127.0.0.1）                │
│           ▼                                           │
│  Python sidecar                                       │
│  ├── FastAPI transport                                │
│  ├── LangGraph workflow                               │
│  ├── model / retrieval adapters                       │
│  ├── SQLite store + checkpointer                      │
│  └── export service                                   │
│                                                       │
└───────────────────────────────────────────────────────┘
```

原则：

- LangGraph state 是会话业务状态的唯一真源。
- assistant-ui 只负责展示和交互，不自行复制 Agent 状态机。
- SQLite 由 Python sidecar 单独写入；前端不得直接打开数据库。
- Tauri 负责启动、监控并关闭 sidecar，不承担模型编排。
- 前后端使用显式事件协议，不把内部 Python 对象直接序列化给 UI。

## 4. 仓库结构

在现有工作区内创建：

```text
maieutic-agent/
├── 知识激发智能体_实现规格.md
├── 桌面端实现说明_CodingAgent.md
├── apps/
│   └── desktop/
│       ├── package.json
│       ├── vite.config.ts
│       ├── src/
│       │   ├── app/
│       │   ├── components/
│       │   │   ├── conversation/
│       │   │   ├── sources/
│       │   │   ├── candidates/
│       │   │   ├── challenges/
│       │   │   └── learning/
│       │   ├── runtime/
│       │   │   ├── assistantRuntime.ts
│       │   │   ├── eventReducer.ts
│       │   │   └── apiClient.ts
│       │   ├── stores/
│       │   └── types/
│       └── src-tauri/
│           ├── tauri.conf.json
│           ├── capabilities/
│           ├── src/
│           └── binaries/          # 构建产物，不提交二进制
├── backend/
│   ├── pyproject.toml
│   ├── src/kel/
│   │   ├── api.py
│   │   ├── graph.py
│   │   ├── models.py
│   │   ├── events.py
│   │   ├── store.py
│   │   ├── security.py
│   │   ├── nodes/
│   │   └── prompts/
│   └── tests/
├── schemas/
│   └── events.schema.json
├── scripts/
│   ├── build_sidecar.sh
│   └── build_sidecar.ps1
└── .github/workflows/
    ├── test.yml
    └── release-desktop.yml
```

前后端共享协议以 `schemas/events.schema.json` 为准。由 JSON Schema 生成 TypeScript 类型；Python 端用 Pydantic 校验。不要维护两套手写、可能漂移的事件类型。

## 5. 进程启动与通信

### 5.1 Sidecar 启动

Tauri 启动 Python sidecar 时传入：

- 随机可用端口；
- 每次启动重新生成的 256-bit session token；
- 应用数据目录；
- 日志等级；
- 父进程标识或退出信号通道。

禁止固定复用公开端口。sidecar 仅监听 `127.0.0.1`，不得监听 `0.0.0.0`。前端请求必须携带 `Authorization: Bearer <session-token>`。

推荐启动协议：

1. Tauri 让操作系统分配回环端口并保持监听，或由 sidecar 绑定端口 `0` 后通过受控进程管道报告实际端口，避免“先选择、后绑定”的竞态。
2. sidecar 完成数据库迁移和图编译。
3. sidecar 向 stdout 输出一行机器可读的 ready 事件，不输出 token。
4. Tauri 使用 ready 事件中的实际端口轮询 `/health`，成功后加载主界面。
5. sidecar 异常退出时显示可恢复错误，不无限静默重启。
6. 应用退出时先请求 `/shutdown`，超时后终止其子进程。

### 5.2 API

MVP API：

```text
GET    /health
POST   /v1/sessions
GET    /v1/sessions
GET    /v1/sessions/{session_id}
DELETE /v1/sessions/{session_id}
POST   /v1/sessions/{session_id}/messages
GET    /v1/sessions/{session_id}/events
POST   /v1/sessions/{session_id}/resume
POST   /v1/sessions/{session_id}/cancel
POST   /v1/sessions/{session_id}/attachments
GET    /v1/sessions/{session_id}/sources
GET    /v1/sessions/{session_id}/candidates
POST   /v1/sessions/{session_id}/candidates/{candidate_id}/decision
POST   /v1/sessions/{session_id}/export
POST   /shutdown
```

`messages` 创建一次 run 并返回 `run_id`。`events` 使用 SSE 流式返回；MVP 不引入 WebSocket。interrupt 通过 `resume` 提交，不能伪装成普通聊天消息。

### 5.3 SSE 事件协议

所有事件包含：

```json
{
  "schema_version": "1",
  "event_id": "evt_...",
  "session_id": "sess_...",
  "run_id": "run_...",
  "sequence": 12,
  "type": "candidate.updated",
  "timestamp": "2026-09-21T10:00:00Z",
  "payload": {}
}
```

首批事件类型：

```text
run.started
phase.changed
message.delta
message.completed
source.added
candidate.created
candidate.updated
challenge.created
claim.updated
interrupt.requested
interrupt.resolved
run.completed
run.failed
run.cancelled
```

约束：

- 同一 run 的 `sequence` 严格递增。
- 前端 reducer 按 `(run_id, sequence)` 幂等处理。
- SSE 重连通过 `Last-Event-ID` 补发，不能重新运行图。
- `message.delta` 只传增量；`message.completed` 传最终规范化消息。
- `run.failed` 返回用户可读错误码，不发送密钥、堆栈或原始模型请求。

## 6. LangGraph 状态与节点

以主规格中的 `AgentState` 为基础，增加运行字段：

```python
class AgentState(TypedDict):
    session_id: str
    run_id: str
    phase: str
    task_type: str
    depth: Literal["fast", "deep"]
    desired_output: str
    user_context: dict[str, Any]
    value_criteria: list[ValueCriterion]
    evidence_items: list[EvidenceItem]
    candidates: list[Candidate]
    claims: list[Claim]
    pending_interrupt: InterruptPayload | None
    messages: list[Message]
    budget: Budget
    stop_reason: str | None
```

MVP 节点顺序：

```text
task_frame
  → depth_router
  → [fast_answer → finalize]
  → [clarify → source → diverge → challenge → synthesize
       → optional_learn_check → finalize]
```

实现要求：

- 每个节点只承担一个业务职责。
- 每次进入节点发出 `phase.changed`。
- 外部调用配置超时、有限重试和取消传播。
- interrupt 之前不执行不可幂等副作用。
- 节点重放时沿用稳定 ID，不重新创建 candidate/source。
- 模型生成候选与模型评分使用不同调用和提示契约。
- 事实、推断、模型候选和未知项分别建模。

## 7. assistant-ui 适配

先验证 `@assistant-ui/react-langgraph` 是否与选定的自托管 LangGraph Server 协议完全兼容。若兼容，使用官方 runtime；若不兼容，实现自定义 runtime adapter。不得为了迎合组件而削弱 interrupt、candidate 或 source 语义。

adapter 职责：

- 用户消息转为 `POST /messages`；
- 将 `message.delta` 映射为流式 assistant message；
- 将 interrupt 映射为可交互 message part；
- 取消生成时调用 `/cancel`；
- 根据 session 列表实现 thread adapter；
- attachment 先上传，消息中只传 attachment ID；
- candidate、source、challenge 进入自定义 message part 或右侧工作区。

禁止前端根据自然语言解析“这是来源/候选/反例”。这些内容必须来自结构化事件。

## 8. UI 规格

### 8.1 主布局

```text
┌──────────────┬──────────────────────────┬──────────────────────┐
│ 会话列表     │ 对话与学习检查           │ 知识工作区           │
│              │                          │                      │
│ 新建会话     │ 消息流                   │ 目标 / 来源           │
│ 历史会话     │ interrupt 表单           │ 候选对比              │
│              │ 输入框 + 附件            │ 边界 / 未知项         │
└──────────────┴──────────────────────────┴──────────────────────┘
```

小窗口时，右侧工作区变为抽屉；不得简单隐藏。

### 8.2 必需组件

`TaskFrameCard`

- 展示目标、任务类型、fast/deep 和价值标准；
- 用户可以修正目标，修正后开启新 run，不篡改旧回放。

`SourceCard`

- 展示标题、来源等级、定位、版本和被哪些 Claim 使用；
- 明显区分 `primary`、`secondary`、`model_only`；
- 点击打开原文件、URL 或内容片段；外链打开前提示域名。

`CandidateComparison`

- 并排展示 2～5 个候选；
- 固定列为核心想法、关键差异、依据、假设、失败模式、验证方法；
- 支持保留、淘汰、组合和用户备注；
- 不用单一总分掩盖各维度差异。

`ChallengeCard`

- 展示反例或边界；
- 用户可选择成立、不成立、部分成立、未知；
- 用户裁决与模型提议分别标识。

`LearningCheck`

- 支持解释、预测、最小练习和实现任务；
- 默认不把选择题正确率等同于掌握；
- 反馈指出具体误解，并回链到解释或来源。

`PhaseIndicator`

- 只显示当前阶段和用户可理解的进度；
- 不展示隐藏思维链或伪造的“模型思考过程”。

### 8.3 空状态和错误状态

- 首屏提供开放输入，不强制用户先选择场景。
- 示例只做提示：巩固 Python、学习 Unity、理解 LangGraph、比较架构、头脑风暴。
- 无来源时明确显示“模型已有知识，未核验”。
- 检索失败不阻塞全部回答，允许降级并标注。
- sidecar 不可用时提供重试、查看本地日志目录和安全退出。
- 模型密钥缺失时进入设置页，不让应用崩溃。

## 9. 文件与资料导入

MVP 支持：`.txt`、`.md`、`.pdf`、常见源代码文本。`.docx` 和网页抓取可后置。

流程：

1. Tauri 文件选择器返回用户明确选择的路径。
2. 前端上传到 sidecar，sidecar 复制到应用数据目录的受控附件区。
3. 解析器生成 attachment、chunks 和 source locators。
4. 原始文件保留哈希、名称、MIME、大小和导入时间。
5. 用户删除会话时，按引用计数清理不再使用的附件。

安全约束：

- 不执行导入文件中的脚本、宏或嵌入对象。
- 解析器设置文件大小、页数、解压尺寸和超时限制。
- Markdown 和模型输出按不可信内容渲染，禁用任意 HTML。
- 本地文件内容未经用户明确操作不得发往非所选模型服务。
- UI 必须说明当前模型服务和资料是否会离开本机。

## 10. 模型与检索适配

定义统一接口，不在 LangGraph 节点中直接依赖某个供应商 SDK：

```python
class ChatModelAdapter(Protocol):
    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]: ...
    async def structured(self, request: ModelRequest, schema: type[T]) -> T: ...

class RetrievalAdapter(Protocol):
    async def search(self, query: SearchQuery) -> list[RetrievedSource]: ...
```

MVP 至少实现一个 OpenAI-compatible adapter。是否支持本地 Ollama 由同一接口扩展，不在 UI 中写死供应商。

密钥处理：

- API key 存入 macOS Keychain / Windows Credential Manager；
- 不写入 SQLite、日志、事件或前端 localStorage；
- 前端只能查询“是否已配置”，不能重新读取明文；
- 导出和错误报告自动剔除认证头、密钥与本地绝对路径。

## 11. SQLite 与迁移

数据库位于 Tauri 应用数据目录。开启 WAL、foreign keys 和 busy timeout。schema 变化必须通过顺序迁移完成，禁止启动时删除重建用户数据库。

核心表沿用主规格，并至少增加：

```text
runs
events
attachments
model_profiles
schema_migrations
```

约束：

- `events(event_id)` 唯一；
- `events(run_id, sequence)` 唯一；
- `runs` 保存 graph checkpoint/thread 对应关系；
- 删除操作使用事务；
- 每次发布前测试从上一个正式版本迁移。

## 12. 隐私与桌面安全

- Tauri capability 使用最小权限，只开放需要的文件选择、sidecar 和外链能力。
- 禁止任意 shell 命令、任意路径读取和远程页面获得 Tauri API 权限。
- CSP 默认拒绝远程脚本；模型输出不能注入脚本。
- sidecar API 使用启动期 token，并校验 Origin/Host。
- URL 打开使用 allowlist 协议，仅允许 `https`，本地文件另走受控命令。
- 日志默认不记录完整用户内容；调试日志必须由用户主动开启。
- 提供删除单会话、删除全部本地数据和导出功能。
- macOS 发布使用签名和 notarization；Windows 使用代码签名。

## 13. 打包与发布

### 13.1 Python sidecar

使用 PyInstaller 或 Nuitka 生成独立可执行文件。二者先做最小 spike，再固定一种；不要同时维护两条长期构建链。

分别构建：

```text
macOS arm64
macOS x86_64（若决定支持 Intel）
Windows x86_64
```

sidecar 二进制由目标平台 CI runner 生成，不能假定交叉编译可用。构建后运行 `/health`、数据库迁移和最小 LangGraph 会话 smoke test。

### 13.2 Tauri 发布

- 开发环境可以调用本地 Python 虚拟环境；正式包只能调用随包 sidecar。
- sidecar 路径使用 Tauri externalBin 解析，不拼接不可信路径。
- CI 生成 `.dmg`/`.app` 与 Windows 安装包。
- 自动更新在 MVP 稳定后启用；启用时必须校验签名。
- 发布产物附 SBOM、第三方许可证清单和校验和。

## 14. 实施顺序

### M0：技术探针

- 建立最小 Tauri + React 应用；
- 启动 Python sidecar 并通过带 token 的 `/health`；
- 从 LangGraph 流式返回一条消息；
- 验证打包后的 macOS arm64 产物。

通过条件：从安装包启动，不依赖系统 Python，不弹出终端窗口，退出后无残留 sidecar。

### M1：单会话闭环

- task frame、fast/deep 路由；
- SSE 流式消息与取消；
- SQLite 会话和事件持久化；
- assistant-ui runtime adapter。

### M2：知识工作区

- SourceCard；
- CandidateComparison；
- ChallengeCard；
- 结构化事件与 replay。

### M3：中断与学习检查

- LangGraph interrupt/resume；
- LearningCheck；
- 应用重启后恢复 pending interrupt；
- 过期、重复和并发 resume 防护。

### M4：资料与导出

- 文件导入、解析和来源定位；
- summary、graph 和 replay 导出；
- 本地数据删除与隐私提示。

### M5：跨平台发布

- Windows sidecar 和安装器；
- macOS 签名/notarization；
- Windows 签名；
- 升级与数据库迁移测试；
- 第三方许可证审计。

## 15. 测试要求

后端：

- 节点单元测试使用固定模型响应，不调用真实网络；
- EIG、评分聚合、来源分级和停止判定使用纯代码测试；
- API 测试覆盖认证、SSE 重连、取消、resume 幂等和附件限制；
- migration 测试保留真实旧版 fixture。

前端：

- reducer 测试乱序、重复和断线重连事件；
- 组件测试覆盖来源等级、候选决策、interrupt 和错误状态；
- 禁止把模型 Markdown 当可信 HTML 渲染；
- E2E 覆盖新建会话、生成、取消、恢复、重启恢复和导出。

发布 smoke test：

- 在干净 macOS/Windows 用户环境安装；
- 不安装 Python、Node 或开发工具也可运行；
- 路径包含空格和非 ASCII 字符时可运行；
- 离线启动可访问历史数据；
- 应用退出后无监听端口和残留进程。

## 16. MVP 验收

只有以下条件全部满足才算桌面 MVP 完成：

1. macOS 安装包可独立启动，Windows 构建链已跑通；
2. 用户可以发起 fast 或 deep 会话并看到流式结果；
3. deep 会话能展示来源、至少两个实质不同的候选及其边界；
4. interrupt 可在应用重启后恢复，且不会重复运行前置节点；
5. 关键事实明确区分 `primary`、`secondary` 和 `model_only`；
6. 文件不会未经授权发送给其他模型服务；
7. 会话可导出、删除，密钥不出现在数据库和日志中；
8. 安装包无需系统 Python/Node，关闭后无残留 sidecar；
9. 与普通单次直答相比，试用评审认为输出增加了可行动的新信息，而非仅增加长度。

## 17. Coding Agent 工作规则

- 先完成 M0 技术探针，再搭建完整页面；sidecar 打包不可行会改变整体方案。
- 每次只实现一个里程碑，并在进入下一里程碑前运行对应测试。
- 不改写 `知识激发智能体_实现规格.md` 中的产品语义；发现冲突时记录并请求决策。
- 不引入第二套 Agent runtime、第二个数据库写入方或前端自建业务状态机。
- 不因为组件方便而把 structured event 降级为 Markdown 文本解析。
- 不在没有来源时生成虚假引用；使用 `model_only` 明示降级。
- 不提交二进制、密钥、用户数据、签名证书或构建缓存。
- 新增依赖前检查维护状态和许可证，并锁定精确版本。
- 修改完成后至少运行受影响层的单元测试、类型检查和一个安装包 smoke test。
