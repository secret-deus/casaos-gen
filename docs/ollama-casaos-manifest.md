# Ollama CasaOS/AppStore 清单优化摘要

## 本次产出

- 新增 CasaOS/AppStore 兼容的 `docker-compose.yml` 模板：`ollama.casaos.yml`

## 依据的规则（来自你给的注释）

- `name`、`services.<service>`、`x-casaos.main` 统一全小写，且保持一致
- 镜像优先指定版本号（避免 `latest`）
- 统一 `restart: unless-stopped`
- 单应用优先使用 `network_mode: bridge`（不额外声明自定义 network）
- `ports[].published` 必须用引号包裹，并随机选择一个 `<30000` 的端口；同时与 `x-casaos.port_map` 保持一致
- 数据卷统一落在 `/DATA/AppData/$AppID/` 下（其中 `$AppID = name`）
- 时区变量写成 `TZ: $TZ`（权限变量则写成 `$PUID/$PGID`，本应用未使用）

## 主要调整点

### 1) 去掉与 Ollama 无关的复合应用片段

- 移除了示例中不相关的 `ollama-db`（MariaDB）服务
- 移除了示例中明显属于 Wallabag 的环境变量与安装提示（`SYMFONY__ENV__*`、Wallabag 默认账号等内容）

> 目的：让模板语义更准确，避免“看起来能跑但实际配置错位”的问题。

### 2) 按 CasaOS/AppStore 规范整理服务字段

- 镜像固定为 `ollama/ollama:0.9.5`
- `restart` 统一为 `unless-stopped`
- 单应用使用 `network_mode: bridge`
- 端口改为 long syntax，并将宿主端口设置为 `"25661"`（小于 30000，且使用双引号）
  - 同步 `x-casaos.port_map: "25661"`
- 数据卷使用 bind mount：
  - `source: /DATA/AppData/$AppID`
  - `target: /root/.ollama`
- 环境变量按约定补齐：
  - `TZ: $TZ`
  - `OLLAMA_HOST: 0.0.0.0:11434`（确保对外监听）

### 3) 补齐 CasaOS 元数据与多语言文案

- 为 `x-casaos` 增加了双语（`en_US`/`zh_CN`）的：
  - `title`、`tagline`、`description`、`tips.before_install`
- 为服务侧 `x-casaos` 增加了端口/卷/环境变量说明（同样双语）

## 验证方式

- YAML 可解析：
  - `python -c "import yaml; from pathlib import Path; yaml.safe_load(Path('ollama.casaos.yml').read_text(encoding='utf-8')); print('YAML OK')"`
- 单元测试通过：
  - `python -m unittest discover -s tests`

## 可选后续优化（如需要）

- `tips` 里如果不想写死 `"25661"`，可以改成占位符风格（与 `port_map` 同步），让模板更通用。
- 如果你希望加健康检查，需要确认镜像内是否自带 `curl/wget`，以及选择稳定的 Ollama API 路径再写 `healthcheck.test`（避免“健康检查本身失败导致容器不健康”）。

