# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

CasaOS Compose Generator 是一个命令行工具，用于将标准 `docker-compose.yml` 文件转换为符合 CasaOS 规范的多语言配置文件。项目采用两阶段架构：Stage 1 使用 LLM 生成英文描述，Stage 2 将其扩展为多语言结构。

## 核心架构原则

1. **结构与内容分离**：本地代码负责结构推断（主服务、端口、分类等），LLM 仅负责文本内容生成
2. **强类型校验**：使用 Pydantic 模型（`CasaOSMeta`）确保数据结构稳定可靠
3. **模块化设计**：解析、LLM 调用、多语言扩展、YAML 输出各自独立
4. **增量更新支持**：通过版本管理实现智能差异检测和描述保留

详细架构设计参见 `smartconvert/develop.md`。

## 常用命令

### 开发环境

```bash
# 安装依赖（推荐使用 uv）
uv sync

# 或使用 pip
pip install -r requirements.txt

# 运行测试
python -m unittest discover -s tests
```

### CLI 工具使用

```bash
# 完整流程：Compose -> LLM -> CasaOS YAML
uv run casaos-gen ./docker-compose.yml --output casaos-compose.yml --stage all

# 仅运行 Stage 1（LLM 生成描述）
uv run casaos-gen ./docker-compose.yml --stage 1 --meta-output meta.json

# 仅运行 Stage 2（多语言扩展）
uv run casaos-gen ./docker-compose.yml --stage 2 --meta-input meta.json

# 生成 params.yml 模板
uv run casaos-gen ./docker-compose.yml --stage params --params-output params.yml

# 使用 params 覆盖元数据
uv run casaos-gen ./docker-compose.yml --params params.yml --stage all

# AppStore 格式输出（规范化 ports/volumes）
uv run casaos-gen ./docker-compose.yml --appstore --params params.yml

# 增量更新模式（保留现有描述）
uv run casaos-gen ./docker-compose.yml --incremental

# 强制完全重新生成
uv run casaos-gen ./docker-compose.yml --force-regenerate

# 版本管理
uv run casaos-gen --list-versions
uv run casaos-gen --show-diff ./docker-compose.yml
uv run casaos-gen --rollback meta.20260108_143022.json
```

### Web UI

```bash
# 启动 Web 界面
uv run casaos-gen-web

# 或
python -m casaos_gen.webui
```

Web UI 默认运行在 `http://localhost:8000`，提供：
- 上传 compose 文件
- 配置 LLM 端点（Base URL、API Key、Model、Temperature）
- 在线编辑元数据字段
- 导出 CasaOS YAML

## 核心模块说明

### 数据流管道

```
docker-compose.yml
    ↓
parser.py (解析 + 推断结构)
    ↓
models.py (CasaOSMeta 骨架)
    ↓
llm_stage1.py (LLM 填充英文描述)
    ↓
i18n.py (多语言扩展)
    ↓
yaml_out.py (生成最终 YAML)
```

### 关键文件

- **`casaos_gen/models.py`**: Pydantic 数据模型定义（`CasaOSMeta`, `AppMeta`, `ServiceMeta` 等）
- **`casaos_gen/parser.py`**: Compose 解析与结构推断（主服务、端口、分类、author）
- **`casaos_gen/infer.py`**: 推断逻辑实现（分类规则、端口优先级等）
- **`casaos_gen/llm_stage1.py`**: Stage 1 LLM 调用与 Prompt 构建
- **`casaos_gen/llm_translate.py`**: LLM 翻译功能（可选的自动多语言翻译）
- **`casaos_gen/i18n.py`**: 多语言包装与翻译表管理
- **`casaos_gen/yaml_out.py`**: 最终 YAML 输出构建
- **`casaos_gen/pipeline.py`**: 高层流程编排与辅助函数
- **`casaos_gen/incremental.py`**: 增量更新与版本管理
- **`casaos_gen/diff_engine.py`**: Compose 差异检测引擎
- **`casaos_gen/version_manager.py`**: 元数据版本控制
- **`casaos_gen/compose_normalize.py`**: AppStore 格式规范化
- **`casaos_gen/template_stage.py`**: 模板生成（不调用 LLM）
- **`casaos_gen/cli.py`**: CLI 入口与参数解析
- **`casaos_gen/webui.py`**: FastAPI Web UI 实现
- **`casaos_gen/constants.py`**: 常量定义（CDN 路径、默认值等）

### 前端

- **`frontend/app.jsx`**: React 单页应用（卡片式 UI）
- **`frontend/index.html`**: HTML 入口

## 开发注意事项

### LLM 集成

- Stage 1 使用 OpenAI Chat Completions API（兼容格式）
- 支持自定义 Base URL（如 Ollama、vLLM 等本地部署）
- Prompt 设计严格禁止 LLM 修改结构，仅填充文本字段
- 使用 Pydantic 校验确保 LLM 输出符合 Schema

### 多语言处理

- 默认支持 15 种语言：`de_DE, el_GR, en_GB, en_US, fr_FR, hr_HR, it_IT, ja_JP, ko_KR, nb_NO, pt_PT, ru_RU, sv_SE, tr_TR, zh_CN`
- 短文本（< 60 字符）优先查翻译表 `casaos_gen/translations.yml`
- 长文本默认仅保留英文，可选启用 LLM 自动翻译（`--auto-translate`）
- 翻译表可通过 `--translations` 参数自定义

### 增量更新机制

- 工作目录默认为 `.casaos-gen/`，存储历史版本
- 自动检测 compose 变更（新增/删除/修改服务、环境变量、端口、卷）
- 保留未变更部分的现有描述，仅对新增/修改部分调用 LLM
- 支持版本回滚和差异对比

### AppStore 格式

- 使用 `--appstore` 标志启用
- 自动规范化 `ports` 为 long syntax
- 自动规范化 `volumes` 为 bind mount，路径统一为 `/DATA/AppData/$AppID/...`
- 需要在 `params.yml` 中指定 `app.store_folder`

### Params 配置

`params.yml` 用于覆盖自动推断的元数据：

```yaml
app:
  store_folder: MyApp        # CDN 目录名（必需）
  author: IceWhaleTech       # 原作者
  developer: fromxiaobai     # 开发者（可选）
  architectures: [amd64, arm64]
  title: My Application
  tagline: Short description
  description: |
    Long description here.
  category: Utilities
  icon: https://cdn.example.com/icon.png
  thumbnail: https://cdn.example.com/thumb.png
  screenshot_link:
    - https://cdn.example.com/screenshot-1.png

services:
  web:
    envs:
      - container: PORT
        description: Application port
    ports:
      - container: "8080"
        description: Web interface
    volumes:
      - container: /data
        description: Application data
```

多语言字段支持：
- 单语言字符串（自动复制到所有语言）
- 多语言字典：`{en_US: "English", zh_CN: "中文"}`

### 测试

- 测试文件位于 `tests/` 目录
- 使用 Python 标准库 `unittest`
- 运行测试：`python -m unittest discover -s tests`

### 日志

- 使用标准 `logging` 模块
- `--verbose` 标志启用 DEBUG 级别日志
- 关键日志点：推断结果、LLM 调用、Schema 校验、文件写入

## Web UI API 端点

标准流程（推荐）：
- `POST /api/compose` - 上传 compose 构建元数据骨架
- `POST /api/meta/fill` - 填充元数据（`mode=llm` 或 `mode=params`）
- `POST /api/render` - 渲染为多语言 YAML
- `POST /api/export` - 导出最终 YAML

已弃用（保留向后兼容）：
- `/api/upload`
- `/api/template`

## 环境变量

- `OPENAI_API_KEY`: OpenAI API 密钥（Stage 1 必需，除非使用自定义 Base URL）
- Web UI 的 LLM 配置持久化在 `llm_config.json`

## 项目依赖

核心依赖：
- `openai>=1.51.0` - LLM API 客户端
- `pydantic>=2.9.2` - 数据模型与校验
- `PyYAML>=6.0.2` - YAML 解析与生成
- `fastapi>=0.115.5` - Web UI 框架
- `uvicorn>=0.32.0` - ASGI 服务器
- `python-multipart>=0.0.9` - 文件上传支持

## 常见问题排查

1. **LLM 返回格式错误**：检查 Prompt 是否明确禁止 Markdown 代码块，确保返回纯 JSON
2. **Schema 校验失败**：查看日志中的 Pydantic 错误详情，通常是 LLM 添加/删除了字段
3. **翻译表未生效**：确认 `translations.yml` 格式正确，key 必须与英文文本完全匹配
4. **增量更新未保留描述**：检查 `.casaos-gen/` 目录是否存在历史版本
5. **AppStore 格式问题**：确保 `params.yml` 中设置了 `app.store_folder`

## 代码风格

- 使用 Python 3.10+ 特性（类型注解、match 语句等）
- 遵循 PEP 8 代码风格
- 函数使用类型提示
- 模块级 docstring 说明模块用途
- 复杂逻辑添加注释说明
