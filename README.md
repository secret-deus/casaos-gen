# CasaOS Compose Generator

A command-line helper that converts existing `docker-compose.yml` files into CasaOS-compatible manifests enriched with multi-language metadata. It follows the architecture in `smartconvert/develop.md`, keeping structural inference local while delegating text generation to LLMs.

一个命令行工具，用于把已有的 `docker-compose.yml` 自动转换为符合 CasaOS 规范的配置，并在需要的字段上生成多语言描述；结构推断在本地完成，文本由 LLM 填充。

## Features / 功能

- Parse docker-compose services, infer the main service/port/category/author, and build a typed CasaOS metadata skeleton.  
  解析 compose 服务，推断主服务、端口、分类和作者信息，并生成结构化的 CasaOS 元数据骨架。
- Stage 1 prompts an LLM (OpenAI Chat Completions) to fill application, environment, port, and volume descriptions, then immediately expands them across all locales.  
  第一阶段通过 OpenAI Chat Completions 生成应用及 env/port/volume 的英文描述。
- Stage 2 wraps descriptions in the CasaOS multi-language format using a translation table for short strings.  
  第二阶段将描述包装为 CasaOS 多语言结构，并可借助翻译表复用常见短语。
- Optional dry-run preview prints the final YAML without writing to disk.  
  可使用 dry-run 预览生成的 YAML，而无需落盘。
- Supports saving/loading intermediate CasaOS metadata JSON between stages.  
  支持在两个阶段之间保存与加载 `CasaOSMeta` JSON。

## Installation / 安装

```bash
uv sync              # 推荐
# 或者
pip install -r requirements.txt
```

Before running Stage 1, set `OPENAI_API_KEY`.  
在执行第一阶段前需要设置 `OPENAI_API_KEY` 环境变量。

## CLI Usage / 命令示例

```bash
# 完整流程：Compose -> LLM -> CasaOS YAML
uv run casaos-gen ./docker-compose.yml \
  --output casaos-compose.yml \
  --model gpt-4.1-mini \
  --stage all

# AppStore-style output (ports/volumes use long/bind syntax under /DATA/AppData/$AppID)
uv run casaos-gen ./docker-compose.yml \
  --output casaos-compose.yml \
  --model gpt-4.1-mini \
  --stage all \
  --appstore \
  --params params.yml

# 仅运行 Stage 1，并导出中间 JSON（同时输出含多语言的 compose）
uv run casaos-gen ./docker-compose.yml --stage 1 --meta-output meta.json

# 仅运行 Stage 2，复用已有 JSON
uv run casaos-gen ./docker-compose.yml --stage 2 --meta-input meta.json

# 生成 params.yml 模板（程序构造，用户再补充字段）
uv run casaos-gen ./docker-compose.yml \
  --stage params \
  --params-output params.generated.yml

# 仅生成模板（不调用 LLM）：普通 compose + params -> CasaOS 模板
uv run casaos-gen ./docker-compose.yml \
  --stage template \
  --params params.generated.yml \
  --output casaos-template.yml

# Post-process an already generated CasaOS compose (no LLM; keeps existing descriptions)
uv run casaos-gen ./casaos-compose.yml \
  --stage normalize \
  --output casaos-compose.appstore.yml \
  --params params.yml
```

Key options / 主要参数：

| Flag | Description |
| ---- | ----------- |
| `--stage` | `1` / `2` / `all` / `template` / `params` selects the pipeline stage；选择执行阶段。 |
| `--params` | YAML overrides for `--stage template` (app/service metadata). |
| `--params-output` | Where to write the generated params file for `--stage params`. |
| `--languages` | Override locales list for stage 2/template；默认使用内置 CasaOS 语言列表。 |
| `--model`, `--temperature` | OpenAI Chat Completions settings for Stage 1；第一阶段使用的模型与温度。 |
| `--meta-output`, `--meta-input` | Persist/reuse the CasaOS metadata JSON；保存或读取 Stage 1 结果。 |
| `--translations` | Override translation table path；自定义翻译表的路径。 |
| `--dry-run` | Print YAML to stdout without writing 文件。 |
| `--verbose` | Enable debug logging；输出调试日志。 |

Stage 2 默认输出以下语言（可用 `--languages` 覆盖）：  
`de_DE, el_GR, en_GB, en_US, fr_FR, hr_HR, it_IT, ja_JP, ko_KR, nb_NO, pt_PT, ru_RU, sv_SE, tr_TR, zh_CN`

## Template Params / Template 配置

当使用 `--stage template` 时，可以提供一个 `params.yml` 来填写必须的 CasaOS 字段并覆盖单个服务的元数据。

最小示例：
```yaml
app:
  store_folder: RagFlow     # CDN 目录名（用于 icon/screenshot/thumbnail 固定链接）
  author: IceWhaleTech      # GitHub 原作者
  developer: fromxiaobai    # 可省略，默认 fromxiaobai
  architectures: [amd64, arm64]  # 可省略，默认 amd64/arm64
  title: RagFlow
  tagline: Deep document RAG
  description: |
    Long description here.
services:
  web:
    envs:
      - container: TZ
        description: Time Zone
```

多语言字段（`title` / `tagline` / `description` 以及 env/port/volume 的 `description`）支持：
- 单语言字符串（自动复制到全部语言）
- 多语言字典（如 `{en_US: "...", zh_CN: "..."}`）

## Translation Map / 翻译表

Short phrases (port names, env hints, etc.) can be pre-translated via `casaos_gen/translations.yml`, or by passing a custom file.  
常用短语可预先写入 `casaos_gen/translations.yml`，也可通过 `--translations` 指定自定义文件。

## Development / 开发

- Core modules live under `casaos_gen/` (parser, LLM stage, i18n, YAML output).  
  核心逻辑位于 `casaos_gen/`，涵盖解析、LLM、国际化及 YAML 输出。
- Tests rely on `unittest`：  
  使用 `unittest` 运行：

```bash
python -m unittest discover -s tests
```

Refer to `smartconvert/develop.md` for the comprehensive design notes.  
完整架构说明请查看 `smartconvert/develop.md`。

## Standard Pipeline / 标准流程

The Web UI uses a single Compose -> Meta -> Render flow:

1) `POST /api/compose` upload compose to build the metadata skeleton.
2) `POST /api/meta/fill` fill metadata:
   - `mode=llm` with optional `model`, `temperature`, `llm_base_url`, `llm_api_key`
   - `mode=params` with optional `params_file`
3) `POST /api/render` expand metadata into `x-casaos` multi-language output.
4) `POST /api/export` return the final YAML.

Deprecated endpoints (kept for backward compatibility):
- `/api/upload`
- `/api/template`

## Web UI / 图形界面

Run `uv run casaos-gen-web` (or `python -m casaos_gen.webui`) to start a local FastAPI server with a React-based card UI for uploading compose files, configuring LLM endpoints, editing metadata, and exporting the Stage 2 YAML.  
运行 `uv run casaos-gen-web`（或 `python -m casaos_gen.webui`）即可启动 React 卡片式 FastAPI WebUI，可上传 compose、配置 LLM、在线修改字段并导出 Stage 2 结果。

- Upload + LLM config: choose `.yml/.yaml`, decide whether to run Stage 1, and supply custom LLM Base URL/API Key/Model/Temperature.  
  上传 compose 时可同时配置 LLM Base URL、API Key、模型、温度，并选择是否执行 Stage 1。
- Stage 1 editing: specify `app.title`, `service:NAME:env:KEY`, etc., with an option to propagate short text to every language via the translation table.  
  通过 `app` 或 `service` 目标字段修改描述，并可勾选“同步全部语言”，自动写入翻译表。
- Stage 2 editing: enter targets like `service:web:port:8080`; the provided text is replicated to **all** locales so you only edit once. Existing CasaOS YAML uploads are preserved and only the chosen field updates.  
  Stage 2 部分现在拆成 **单语言** 和 **多语言** 两个卡片：`app.category`/`service:web:index` 等在单语言卡片里编辑；`app.title`、`app.tips.before_install`、`service:web:port:8080` 等多语言字段在另一个卡片一次输入即可自动同步到全部语言。
- Export YAML: trigger Stage 2 to generate CasaOS YAML directly in the UI textarea.  
  在界面中点击导出即可生成 CasaOS YAML 并复制。
- AppStore format: the WebUI export always normalizes service `ports`/`volumes` into the AppStore-friendly long/bind syntax.  
  AppStore 输出：WebUI 导出结果默认会将服务的 `ports`/`volumes` 规范化为 AppStore 常用的 long/bind 写法。
- WebUI LLM settings persist under `llm_config.json` so you don’t have to re-enter Base URL/API key each session.  
  前端现已提供保存按钮，输入 Base URL / API Key / Model / Temperature 后点击 “Save LLM Settings” 即可写入 `llm_config.json`，以后默认自动加载。
