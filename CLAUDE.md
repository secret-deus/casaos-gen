# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

CasaOS Compose Generator — 将标准 `docker-compose.yml` 转换为符合 CasaOS 规范的多语言配置文件。两阶段架构：Stage 1 通过 LLM 生成英文描述，Stage 2 将其扩展为多语言结构。

详细架构设计参见 `smartconvert/develop.md`。

## 常用命令

```bash
# 安装依赖
uv sync

# 运行全部测试
python -m unittest discover -s tests

# 运行单个测试文件
python -m unittest tests.test_casaos_gen

# 运行单个测试方法
python -m unittest tests.test_casaos_gen.CasaOSParserTests.test_build_casaos_meta_generates_structure

# 完整流程：Compose -> LLM -> CasaOS YAML
uv run casaos-gen ./docker-compose.yml --output casaos-compose.yml --stage all

# 仅生成模板（不调用 LLM）
uv run casaos-gen ./docker-compose.yml --stage template --params params.yml

# 后处理已有 CasaOS compose（仅规范化，不调用 LLM）
uv run casaos-gen ./casaos-compose.yml --stage normalize --params params.yml

# 增量更新（保留已有描述，仅对变更部分调用 LLM）
uv run casaos-gen ./docker-compose.yml --incremental

# 启动 Web UI（http://localhost:8000）
uv run casaos-gen-web
```

## 核心架构

### 设计原则

1. **结构与内容分离**：本地代码负责结构推断（主服务、端口、分类等），LLM 仅负责文本内容生成
2. **强类型校验**：`CasaOSMeta`（Pydantic）作为 Stage 1 和 Stage 2 之间的统一中间格式
3. **翻译分层**：短文本查翻译表 `casaos_gen/translations.yml`，长文本默认仅保留英文，`--auto-translate` 可启用 LLM 翻译

### 数据流管道

```
docker-compose.yml
    ↓ parser.py (解析 + 推断主服务/端口/分类/author)
    ↓ models.py (CasaOSMeta 骨架，description 为空)
    ↓ llm_stage1.py (LLM 填充英文描述) 或 template_stage.py (模板模式，不调 LLM)
    ↓ pipeline.py (apply_params_to_meta 覆盖用户参数)
    ↓ i18n.py (wrap_multilang: 短文本查表，长文本保留英文)
    ↓ yaml_out.py (合并回原 compose，生成 x-casaos)
    ↓ compose_normalize.py (可选: AppStore 格式规范化)
```

### 模块间关系

- **`cli.py`** → 入口，解析参数后分发到不同流程：普通 stage 流程调 `main.py`，增量更新调 `incremental.py`
- **`main.py`** → 编排 `run_stage_one`/`stage_two_from_meta`/`write_final_compose` 等高层函数
- **`pipeline.py`** → Web UI 和 CLI 共用的辅助函数（`build_meta`/`fill_meta_with_llm`/`render_compose`/`apply_params_to_meta`）
- **`webui.py`** → FastAPI 服务，使用全局 `WebState` 保持会话状态，调 `pipeline.py` 处理逻辑
- **`incremental.py`** → 增量更新流程，依赖 `diff_engine.py`（差异检测）和 `version_manager.py`（版本控制）
- **`refine_mode.py`** → AI 润色模式：对 `user_input=True` 的字段保持原意、改进表达

### CasaOSMeta 模型结构

`CasaOSMeta` 是整个管道的核心数据结构（`models.py`）：

```
CasaOSMeta
├── app: AppMeta (title, tagline, description, category, author, developer, main, port_map, icon, thumbnail, screenshot_link, architectures, index, scheme)
└── services: Dict[str, ServiceMeta]
    └── ServiceMeta
        ├── envs: List[EnvItem]     (container, description, user_input, multilang)
        ├── ports: List[PortItem]    (container, description, user_input, multilang)
        └── volumes: List[VolumeItem] (container, description, user_input, multilang)
```

- `user_input: bool` — 标记用户提供的内容，LLM 会润色而非重写
- `multilang: bool` — 控制该字段是否在 Stage 2 做多语言扩展

### 前端架构

React 单页应用（通过 CDN 加载，无构建步骤），位于 `frontend/`。

#### 双模式架构

顶层 `mode` 状态驱动三种视图：

```
mode="landing"  → LandingView（加载 compose 文件）
mode="full"     → FullWorkflowView — 3 步 Stepper（Metadata → Preview → Export）
mode="quick"    → QuickEditView — 单页快速编辑（QuickUpdate + Export，无 Stepper）
```

加载 compose 后弹出模态框让用户选择 Full Workflow 或 Quick Edit。

#### 目录结构

- **`app.jsx`** — 主应用，mode 状态管理、reducer、全局业务逻辑
- **`views/`** — 三种模式视图：
  - `LandingView.jsx` — 包裹 StepLoadCompose，landing 模式
  - `FullWorkflowView.jsx` — 3 步 Stepper + AnimatedContainer 步骤切换动画
  - `QuickEditView.jsx` — QuickUpdateCard + ExportCard 交错入场
- **`steps/`** — 步骤组件：`StepLoadCompose`、`StepMetadata`、`StepPreview`、`StepExport`（含拆分出的 `QuickUpdateCard` 和 `ExportCard`）
- **`components/`** — 复用组件（Button, Card, Form, Tabs, Toast, CodeViewer, Dropzone, Stepper, AnimatedContainer）
- **`styles.css`** — 样式 + CSS 动画系统（viewEnter、stepForward/Backward、cardEnter、toast 进出、modal 动画、skeleton 加载）
- **`index.html`** — 入口，引用所有脚本

## 关键约定

### CLI Stage 参数

| `--stage` | 说明 | 是否调 LLM |
|-----------|------|-----------|
| `all` | 完整流程 | 是 |
| `1` | 仅 Stage 1 + 自动输出多语言 compose | 是 |
| `2` | 仅 Stage 2（需 `--meta-input`） | 否 |
| `template` | 从 params 生成模板 | 否 |
| `params` | 生成 params.yml 骨架 | 否 |
| `normalize` | 仅规范化已有 compose | 否 |

### 多语言

默认 15 种语言：`de_DE, el_GR, en_GB, en_US, fr_FR, hr_HR, it_IT, ja_JP, ko_KR, nb_NO, pt_PT, ru_RU, sv_SE, tr_TR, zh_CN`

翻译策略（`i18n.py:wrap_multilang`）：
- 短文本（< 60 字符且无换行）→ 查 `translations.yml` 翻译表
- 长文本 → 默认仅保留 `en_US`，可用 `--auto-translate` 启用 LLM 批量翻译（`llm_translate.py`）

### AppStore 格式

`--appstore` 标志（配合 `params.yml` 中的 `app.store_folder`）：
- `ports` 规范化为 long syntax
- `volumes` 规范化为 bind mount，路径 `/DATA/AppData/$AppID/...`
- `icon`/`thumbnail`/`screenshot_link` 自动填充 CDN 路径（见 `constants.py:CDN_BASE`）

### 增量更新

工作目录 `.casaos-gen/`：
- `meta.current.json` — 当前元数据
- `compose.hash` — compose 文件 SHA256
- `history/` — 最多 3 个历史版本，自动轮转

### Web UI API 流程

```
POST /api/compose       → 上传 compose，构建元数据骨架
POST /api/meta/fill     → 填充元数据（mode=llm 或 mode=params）
POST /api/render        → 渲染多语言 YAML
POST /api/export        → 导出最终 YAML
```

版本管理 API：`GET /api/versions`、`POST /api/versions/rollback`、`GET /api/diff`、`POST /api/incremental`

Web UI 的 LLM 配置持久化在 `llm_config.json`。

## LLM 集成注意事项

- 使用 OpenAI Chat Completions API 兼容格式，支持自定义 Base URL（Ollama、vLLM 等）
- Prompt 严格禁止 LLM 修改 JSON 结构，仅填充文本字段
- LLM 必须返回纯 JSON（禁止 Markdown 代码块），由 Pydantic 校验
- 环境变量 `OPENAI_API_KEY` 或 Web UI 中配置 API Key

## 常见问题

1. **LLM 返回格式错误**：Prompt 中已禁止 Markdown 代码块，若仍出现则检查 `llm_stage1.py:build_stage1_prompt` 中的指令
2. **Schema 校验失败**：查看 Pydantic 错误详情，通常是 LLM 添加/删除/重命名了字段
3. **翻译表未生效**：`translations.yml` 的 key 必须与英文文本完全匹配（含大小写和空格）
4. **增量更新未保留描述**：确认 `.casaos-gen/` 目录存在且含 `meta.current.json`
5. **AppStore 格式问题**：`params.yml` 必须设置 `app.store_folder`
