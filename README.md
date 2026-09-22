# 知识激发智能体（maieutic-agent）

一个**本地优先**的知识激发智能体。它不追求“回答更长”，而是通过**任务框定 → 澄清 → 取证分级 → 候选发散 → 反例批判 → 综合 → 学习检查**的流程，产出高信息密度、可追溯、可行动的回答——对抗大模型默认的通识化、低信息量与过早收敛。

成功标准只有一个：相较一次普通直答，是否增加了能改变用户理解、选择或行动的**可靠**信息。

## 能力概览

- **深度/直答自适应**：简单问题直接紧凑作答；复杂、多解、高代价或带资料的问题进入完整深度流程。
- **来源分级**：每条关键事实标注 `primary`（官方文档/论文/源码/用户材料）、`secondary`（教程/综述）、`model_only`（模型已有知识，未核验）。无来源绝不伪造引用。
- **竞争性候选**：对复杂问题生成 2～5 个机制路径不同的候选，各带关键差异、假设、失败模式与最低成本验证，再筛选/组合，而非在第一个常见答案上收敛。
- **反例与边界**：为候选主动寻找失效条件，用户可逐条裁决（成立/不成立/条件/没遇到/无法判断）。
- **可中断可恢复**：基于 LangGraph 动态中断，澄清与学习检查等待用户输入；应用重启后仍可从待回答处恢复，不重复运行前置节点。
- **资料导入与论文检索**：导入本地 txt/md/pdf/源码，或联网检索 arXiv / OpenAlex 论文并下载全文，命中后作为一手来源参与推理。
- **可回放导出**：每个会话可导出 `summary.md`、`graph.json`（证据→Claim→边界图）、`replay.jsonl`（逐事件回放）。

## 仓库结构

```text
maieutic-agent/
├── backend/            Python sidecar：FastAPI + LangGraph + SQLite
│   ├── src/kel/
│   │   ├── graph.py        LangGraph 状态图（节点顺序的唯一真源）
│   │   ├── nodes/          task_frame / clarify / source / diverge / challenge / synthesize ...
│   │   ├── eig.py          EIG、熵、评分聚合（纯 NumPy，可复现）
│   │   ├── adapters.py     模型与检索适配（OpenAI 兼容 / 本地切片 / 论文）
│   │   ├── papers.py       arXiv + OpenAlex 检索与下载
│   │   ├── store.py        SQLite 持久化与顺序迁移
│   │   ├── api.py          HTTP + SSE（仅回环，启动期 token 鉴权）
│   │   ├── cli.py          对话式终端（rich + prompt_toolkit）
│   │   └── render.py       终端渲染
│   └── tests/          12 个测试文件，纯离线可跑
├── apps/desktop/       Tauri v2 + React 桌面端
│   ├── src/                对话区 + 知识工作区 + 会话/设置
│   └── src-tauri/          Rust 壳：sidecar 生命周期、最小权限
├── schemas/            events.schema.json（前后端共享事件协议，单一真源）
├── scripts/            build_sidecar.sh / .ps1（PyInstaller 打包 + smoke test）
└── .github/workflows/  test.yml（后端/前端/Rust）、release-desktop.yml
```

私有资料（`论文/`、两份设计规格文档）不随仓库分发，见 `.gitignore`。

<!-- PLACEHOLDER_QUICKSTART -->

## 快速开始

### 环境

- Python 3.11（`numpy` 上限受此约束）、Node ≥ 20、Rust stable（仅桌面端需要）
- 一个 OpenAI 兼容的模型服务。默认指向 DeepSeek（`deepseek-chat`，支持结构化 JSON 输出）。

### 后端 + CLI（最快体验）

```bash
cd backend
uv venv --python 3.11 .venv
uv pip install -e ".[dev]"

export KEL_API_KEY=<你的模型密钥>       # 不配则走离线降级，不会生成真实候选
.venv/bin/python -m kel.cli            # 新建会话
.venv/bin/python -m kel.cli --online   # 允许论文检索（检索词会发往 arXiv/OpenAlex）
```

常用命令：`/workspace` 看候选与边界、`/import <路径>` 导入资料、`/papers <关键词>` 检索论文、`/get <编号>` 下载全文、`/decide` `/rule` 裁决、`/export` 导出、`/help` 全部命令。

### 桌面端

```bash
# 1) 先打包 sidecar（onedir + smoke test）
bash scripts/build_sidecar.sh
# 2) 开发模式（调用本地 venv）或正式打包
cd apps/desktop && npm install
KEL_DEV_PYTHON=../../backend/.venv/bin/python npx tauri dev
npx tauri build          # 产出 .app / .dmg / 安装包
```

密钥存入系统钥匙串，不写入 SQLite、日志或前端；应用退出后不残留 sidecar。

## 测试

```bash
cd backend && .venv/bin/python -m pytest -q          # 后端，全离线
cd apps/desktop && npx tsc -b && npx vitest run      # 前端类型检查 + 单测
```

事件协议改动后需重新生成类型，避免前后端漂移：

```bash
backend/.venv/bin/python scripts/gen_schema.py       # 由 Pydantic 生成 schema
cd apps/desktop && npm run gen:types                 # 由 schema 生成 TS 类型
```

## 设计要点

- **LangGraph state 是会话业务状态的唯一真源**；前端只展示、不复制状态机，也不从自然语言解析领域对象——它们只来自结构化事件。
- **生成与评判分离**：候选生成器只制造差异，批判器与评分是独立调用，避免发散时自我审查退回通识。
- **计算可复现**：EIG、熵、评分聚合由代码执行，LLM 只负责生成与语义判断。
- **隐私**：sidecar 仅监听 `127.0.0.1` 且要求启动期 token；本地文件未经明确操作不外发；导出与错误报告自动剔除密钥与绝对路径。

## 许可

私有项目，未附许可协议。

