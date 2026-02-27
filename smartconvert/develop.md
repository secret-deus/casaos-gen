## 一、目标与功能边界

### 1.1 工具目标

实现一个命令行工具，将一个标准 `docker-compose.yml` 自动转换为 **符合 CasaOS 应用规范** 的 `docker-compose.yml`，包含：

1. 完整的 `services` 配置（保留或轻微清洗原配置）。
2. 新增 `x-casaos` 元数据段，包含：

   * 应用级元数据：`title`, `tagline`, `description`, `category`, `main`, `port_map`, `author`, 等。
   * 服务级元数据：每个 service 的 `envs` / `ports` / `volumes` 的描述信息。
3. 支持多语言结构，如：

   ```yaml
   title:
     en_US: "My App"
     zh_CN: "我的应用"
   ```

### 1.2 功能范围

* 输入：标准 `docker-compose.yml` 文件。
* 核心功能：

  1. 自动解析 Compose；
  2. 自动推断 CasaOS 所需结构（主服务、端口映射、分类等）；
  3. 调用 LLM 生成英文文案（标题、简介、参数说明等）；
  4. 将英文文本扩展成多语言结构（短文本查表，多语言可选）。
* 输出：一个带 `x-casaos` 且支持多语言的 `docker-compose.yml`。

---

## 二、总体架构设计

整体流程分为两个主要阶段（Stage 1 + Stage 2），统一由 CLI 调用。

### 2.1 流程图

```text
docker-compose.yml
        │
        ▼
 [解析模块]
  读取并解析 YAML
        │
        ▼
 [结构生成模块]
  构建 CasaOS 元数据骨架 (无描述文本)
        │
        ▼
 [LLM 文案填充模块 - Stage 1]
  为骨架填入英文 title/tagline/description 等
        │
        ▼
 [多语言扩展模块 - Stage 2]
  将英文文本扩展为多语言结构
        │
        ▼
 [YAML 输出模块]
  写入最终 casaos-compose.yml
```

### 2.2 关键原则

1. **结构由本地代码生成，LLM 只负责文本内容**，避免结构不稳定。
2. **强类型 Schema 校验**（使用 `pydantic`）保证 Stage 1 输出稳定可靠。
3. **翻译模块分层**：

   * 短文本：用本地翻译表映射；
   * 长文本：默认仅保留英文，可选调用 LLM 做自动翻译。
4. **模块化**设计：解析、结构生成、LLM 调用、多语言扩展、CLI、日志各自独立，便于维护。

---

## 三、数据模型设计（Schema）

使用 `pydantic` 为 CasaOS 元数据定义数据结构，方便校验与后续扩展。

### 3.1 Service 级元数据模型

```python
from pydantic import BaseModel, Field
from typing import List, Dict

class EnvItem(BaseModel):
    container: str
    description: str  # en_US 文本

class PortItem(BaseModel):
    container: str    # 容器内端口，如 "8080"
    description: str  # en_US 文本

class VolumeItem(BaseModel):
    container: str    # 容器内路径，如 "/data"
    description: str  # en_US 文本

class ServiceMeta(BaseModel):
    envs: List[EnvItem] = Field(default_factory=list)
    ports: List[PortItem] = Field(default_factory=list)
    volumes: List[VolumeItem] = Field(default_factory=list)
```

### 3.2 应用级元数据模型

```python
class AppMeta(BaseModel):
    title: str
    tagline: str
    description: str
    category: str
    author: str
    main: str        # 主 service 的名称
    port_map: str    # 映射到宿主机的主端口，如 "80"
    architectures: List[str] = ["amd64"]
    index: str = "/"
    scheme: str = "http"
```

### 3.3 CasaOS 元数据总模型

```python
class CasaOSMeta(BaseModel):
    app: AppMeta
    services: Dict[str, ServiceMeta]
```

此结构在整个流程中作为中间统一格式：

* Stage 1 的输入：未填描述的骨架 `CasaOSMeta`（或 dict）。
* Stage 1 的输出：填好英文描述的 `CasaOSMeta`。
* Stage 2：基于 `CasaOSMeta` 生成多语言 `x-casaos` 结构。

---

## 四、Stage 1：从 Compose 到英文 CasaOS 元数据

Stage 1 分三步：

1. 解析 Compose；
2. 生成 CasaOS 元数据骨架；
3. LLM 填充英文文案。

### 4.1 Compose 解析模块

职责：

* 使用 `PyYAML` 解析 `docker-compose.yml`:

  ```python
  import yaml

  with open(input_file, "r") as f:
      compose_data = yaml.safe_load(f)
  services = compose_data.get("services", {})
  ```
* 提供一些方便的帮助函数：

  * 枚举服务；
  * 读取每个 service 的 `environment` / `ports` / `volumes`；
  * 标准化端口、卷的表示。

### 4.2 CasaOS 骨架生成模块

负责从 Compose 数据生成一个**纯结构、无描述文本**的 `CasaOSMeta` 对象。

核心逻辑包括：

#### 4.2.1 主服务推断

策略示例（按顺序尝试）：

1. 有暴露 HTTP 常见端口（80、443、8080、3000 等）的服务优先；
2. 如果只有一个服务，则它是主服务；
3. 若有名为 `web`, `frontend`, `app` 等的服务，优先考虑；
4. 若都不满足，取第一个 service。

#### 4.2.2 主端口（`port_map`）推断

从主服务的 `ports` 中：

* 优先使用映射到宿主 80/443/8080 的端口；
* 若不存在，则取第一个映射端口；
* 存储为字符串例如 `"80"`。

#### 4.2.3 分类（`category`）推断

简单规则映射，例如：

```python
CATEGORY_RULES = {
    "mysql": "Database",
    "mariadb": "Database",
    "postgres": "Database",
    "redis": "Database",
    "nginx": "Web Server",
    "apache": "Web Server",
    "ollama": "AI",
    "open-webui": "AI",
    "nextcloud": "Productivity",
    # ...
}
```

匹配方式：

* 根据 image 名 `service.image` 中包含的关键字（lowercase）。

#### 4.2.4 author 推断

* 若 image 类似 `portainer/portainer-ce`，取 `/` 前部分作为 author；
* 否则默认 `"CasaOS User"` 或 `"Unknown"`。

#### 4.2.5 envs/ports/volumes 结构化

对每个 service：

* `environment`：

  * 支持两种格式：列表形式 (`["KEY=value", "A=b"]`) 和字典形式（`{"KEY": "value"}`）。
  * 转成：

    ```python
    EnvItem(container="KEY", description="")
    ```

* `ports`：

  * 格式如 `"8080:8080"` 或 `"80:80/tcp"`，解析容器端口为 `target`。
  * 转成：

    ```python
    PortItem(container="8080", description="")
    ```

* `volumes`：

  * 格式如 `"./data:/data"` 或 `"/mnt/data:/data:ro"`，提取容器路径部分。
  * 转成：

    ```python
    VolumeItem(container="/data", description="")
    ```

#### 4.2.6 组装 CasaOSMeta

骨架示例（未填描述）：

```python
from typing import Dict

def build_casaos_meta(compose_data: dict) -> CasaOSMeta:
    services = compose_data.get("services", {})
    main_service = infer_main_service(services)
    port_map = infer_main_port(services[main_service])
    category = infer_category(services)
    author = infer_author(services)

    app_meta = AppMeta(
        title="",          # 待 LLM 填充
        tagline="",        # 待 LLM 填充
        description="",    # 待 LLM 填充
        category=category,
        author=author,
        main=main_service,
        port_map=str(port_map),
    )

    svc_meta: Dict[str, ServiceMeta] = {}

    for name, svc in services.items():
        env_items = extract_envs(svc)
        port_items = extract_ports(svc)
        vol_items = extract_volumes(svc)
        svc_meta[name] = ServiceMeta(
            envs=env_items,
            ports=port_items,
            volumes=vol_items,
        )

    return CasaOSMeta(app=app_meta, services=svc_meta)
```

### 4.3 LLM 文案填充模块

该模块负责：

1. 将 `CasaOSMeta` 骨架转为 JSON；
2. 构造 Prompt，发送到 LLM；
3. 解析 LLM 返回的 JSON；
4. 经 `CasaOSMeta` 校验后返回。

#### 4.3.1 Prompt 设计

核心要求：

* 明确禁止修改结构；
* 明确只填 `title` / `tagline` / `description` 字段；
* 输出必须是 JSON。

示例（伪代码）：

```python
import json

def build_stage1_prompt(structure: CasaOSMeta) -> str:
    structure_json = structure.model_dump()
    return f"""
You are an expert in generating metadata for CasaOS applications.

I will give you a JSON object representing the structural metadata extracted from a docker-compose.yml file.
The structure is correct and MUST NOT be modified.

Your task:
1. Fill in ONLY the following text fields in English:
   - app.title
   - app.tagline
   - app.description
   - services[*].envs[*].description
   - services[*].ports[*].description
   - services[*].volumes[*].description

2. DO NOT:
   - add new keys
   - remove keys
   - rename keys
   - reorder anything
   - return Markdown or code blocks
   - output YAML

3. Description guidelines:
   - Keep descriptions concise, professional, and accurate.
   - For ports: describe the function (e.g., "Main web interface port").
   - For environment variables: explain their purpose.
   - For volumes: describe the data stored.
   - app.description should include a short introduction and a "Key Features:" section.

Here is the structure to fill:

{json.dumps(structure_json, indent=2)}

Now return ONLY the completed JSON.
"""
```

#### 4.3.2 调用 LLM 及解析

示意代码：

```python
from openai import OpenAI
import json

def run_stage1_llm(structure: CasaOSMeta, model: str = "gpt-4.1-mini") -> CasaOSMeta:
    client = OpenAI()
    prompt = build_stage1_prompt(structure)

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    content = resp.choices[0].message.content.strip()

    # 直接解析 JSON
    data = json.loads(content)

    # 通过 Pydantic 校验
    meta = CasaOSMeta.model_validate(data)
    return meta
```

---

## 五、Stage 2：多语言扩展设计

目标：将 Stage 1 生成的英文 CasaOSMeta 转换为 CasaOS 的多语言 YAML 结构。

### 5.1 翻译配置（TRANSLATION_MAP）

使用一个单独的 `translations.yml` 或 Python dict 存储：

* key：英文短句；
* value：各语言翻译。

示例（Python 形式）：

```python
TRANSLATION_MAP = {
    "API Port": {
        "zh_CN": "API 端口",
        "de_DE": "API-Port",
    },
    "Main web interface port": {
        "zh_CN": "主 Web 界面端口",
        "de_DE": "Haupt-Weboberflächen-Port",
    },
}
```

### 5.2 文本包装函数

根据文本长度与是否在翻译表中，决定多语言结构：

```python
def wrap_multilang(english: str, languages: list[str]) -> dict:
    """
    将英文字符串包装成多语言字典结构:
    - 总是设置 en_US；
    - 对短文本尝试查表；
    - 对长文本默认不伪造翻译。
    """
    result = {"en_US": english}
    is_long = len(english) > 60 or "\n" in english

    for lang in languages:
        if lang == "en_US":
            continue

        if is_long:
            # 长文本默认不自动填充，保留为缺失
            continue

        translations_for_text = TRANSLATION_MAP.get(english)
        if translations_for_text:
            translated = translations_for_text.get(lang)
            if translated:
                result[lang] = translated

    return result
```

### 5.3 应用级字段多语言化

对 `AppMeta` 中的 `title`, `tagline`, `description`：

```python
def apply_multilang_app(meta: CasaOSMeta, languages: list[str]) -> dict:
    app = meta.app
    x_casaos_app = {
        "title":    wrap_multilang(app.title, languages),
        "tagline":  wrap_multilang(app.tagline, languages),
        "description": wrap_multilang(app.description, languages),
        "category": app.category,
        "author":   app.author,
        "main":     app.main,
        "port_map": app.port_map,
        "architectures": app.architectures,
        "index": app.index,
        "scheme": app.scheme,
    }
    return x_casaos_app
```

> 你可以选择：对 `description` 这种长文本只保留 `en_US`，不使用 `wrap_multilang` 的查表逻辑。

### 5.4 服务级字段多语言化

对每个 service 的 `envs/ports/volumes` 的 `description` 做包装：

```python
def apply_multilang_services(meta: CasaOSMeta, languages: list[str]) -> dict:
    services_multilang = {}

    for name, svc_meta in meta.services.items():
        svc_x = {
            "envs": [],
            "ports": [],
            "volumes": [],
        }

        for env in svc_meta.envs:
            svc_x["envs"].append({
                "container": env.container,
                "description": wrap_multilang(env.description, languages),
            })

        for port in svc_meta.ports:
            svc_x["ports"].append({
                "container": port.container,
                "description": wrap_multilang(port.description, languages),
            })

        for vol in svc_meta.volumes:
            svc_x["volumes"].append({
                "container": vol.container,
                "description": wrap_multilang(vol.description, languages),
            })

        services_multilang[name] = svc_x

    return services_multilang
```

### 5.5 生成最终 CasaOS YAML 结构

最终输出结构大致为：

```python
def build_final_compose(
    original_compose: dict,
    meta: CasaOSMeta,
    languages: list[str],
) -> dict:
    compose_out = original_compose.copy()

    # 1) 服务级 x-casaos
    services_x = apply_multilang_services(meta, languages)
    for name, svc in compose_out.get("services", {}).items():
        if name in services_x:
            svc["x-casaos"] = services_x[name]

    # 2) 应用级 x-casaos
    compose_out["x-casaos"] = apply_multilang_app(meta, languages)

    return compose_out
```

---

## 六、命令行工具（CLI）设计

### 6.1 基本命令格式

```bash
casaos-gen my-app-compose.yml \
  --output my-app-casaos.yml \
  --languages en_US zh_CN de_DE \
  --model gpt-4.1-mini \
  --stage all \
  --verbose
```

### 6.2 支持的参数

* 位置参数：

  * `input_file`：输入的 compose 文件路径。
* 选项：

  * `-o, --output`：输出文件路径，默认 `casaos-compose.yml`。
  * `--languages`：语言列表，默认 `en_US zh_CN`。
  * `--stage`：`1` / `2` / `all`：

    * `1`：仅生成英文 CasaOSMeta 并打印或保存；
    * `2`：对已有的 CasaOSMeta JSON 进行多语言扩展；
    * `all`：从原 compose 一条龙生成最终输出。
  * `--model`：LLM 模型名；
  * `--temperature`：LLM 温度；
  * `--dry-run`：只打印到 stdout，不写文件；
  * `--verbose`：输出详细日志。

---

## 七、错误处理与日志

### 7.1 日志

使用标准 `logging`：

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)
```

关键日志点：

* 成功读取 input；
* 推断出的主服务、主端口、分类；
* 调用 LLM 的模型名与参数；
* LLM 返回的 JSON 解析成功 / 失败；
* Pydantic 校验错误细节；
* 最终输出路径。

### 7.2 错误处理

* 输入文件不存在：提示路径错误。
* YAML 解析失败：提示文件不是合法的 compose。
* LLM 调用异常：提示网络/API Key/限流信息。
* JSON 解析失败：打印 LLM 原始输出片段，便于调试。
* Schema 校验失败：打印哪一个字段缺失/类型错误。

---

## 八、工程目录结构建议

```text
casaos_gen/
  ├─ cli.py                 # CLI 入口
  ├─ main.py                # 主流程协调
  ├─ models.py              # Pydantic 数据模型(CasaOSMeta 等)
  ├─ parser.py              # Compose 解析与 CasaOSMeta 骨架生成
  ├─ llm_stage1.py          # Stage 1: LLM 文案填充
  ├─ i18n.py                # 多语言扩展逻辑 & TRANSLATION_MAP 加载
  ├─ yaml_out.py            # 最终 YAML 输出构建
  ├─ translations.yml       # 翻译表
  └─ tests/                 # 单元测试
```

---

## 九、示例端到端流程（简要示意）

1. 用户运行：

   ```bash
   casaos-gen my-app.yml -o my-app-casaos.yml --languages en_US zh_CN
   ```

2. 程序执行：

   * `parser.py` 解析 `my-app.yml` → `CasaOSMeta` 骨架；
   * `llm_stage1.py` 调用 LLM 填充英文 title/description/envs/ports/volumes 描述；
   * 校验后得到完整英文 `CasaOSMeta`；
   * `i18n.py` 包装为多语言结构；
   * `yaml_out.py` 合并回原 compose，生成 `x-casaos` 字段并写入文件。

3. 用户得到一个可以直接导入 CasaOS 的多语言应用定义。

---

## 十、Web UI 前端架构

### 10.1 技术栈

React 18 单页应用，通过 CDN 加载（React、ReactDOM、Babel），无构建步骤。所有 `.jsx` 文件由 Babel Standalone 在浏览器端编译。FastAPI 的 `StaticFiles` 中间件直接服务 `frontend/` 目录。

### 10.2 双模式架构

顶层 `mode` 状态（`"landing"` | `"full"` | `"quick"`）驱动三种独立视图：

```text
Landing (加载 compose)
    ├── 选择 "Full Workflow" → FullWorkflowView
    │     3 步 Stepper: Metadata → Preview → Export
    │     步骤切换有 slideX 动画
    │     step 0 Back 返回 Landing
    │
    └── 选择 "Quick Edit" → QuickEditView
          单页: QuickUpdateCard + ExportCard
          卡片有交错入场动画
```

### 10.3 前端目录结构

```text
frontend/
├── index.html                      # 入口
├── styles.css                      # 全局样式 + CSS 动画系统
├── app.jsx                         # 主应用（mode 状态、reducer、业务逻辑）
├── components/
│   ├── utils.jsx                   # 工具函数（cx, uid, api 等）
│   ├── Button.jsx                  # 按钮组件
│   ├── Card.jsx                    # 卡片组件
│   ├── Form.jsx                    # 表单组件（Field, Input, Select, Textarea, Checkbox）
│   ├── Tabs.jsx                    # 标签页组件
│   ├── Stepper.jsx                 # 步骤条（动态列数）
│   ├── Toast.jsx                   # Toast 通知（支持退出动画）
│   ├── CodeViewer.jsx              # 代码查看器
│   ├── Dropzone.jsx                # 文件拖放区
│   └── AnimatedContainer.jsx       # 通用动画包裹器
├── steps/
│   ├── StepLoadCompose.jsx         # 加载 compose 步骤
│   ├── StepMetadata.jsx            # 元数据配置步骤
│   ├── StepPreview.jsx             # 预览步骤
│   └── StepExport.jsx              # 导出步骤（含 QuickUpdateCard、ExportCard）
└── views/
    ├── LandingView.jsx             # Landing 模式视图
    ├── FullWorkflowView.jsx        # Full Workflow 模式视图
    └── QuickEditView.jsx           # Quick Edit 模式视图
```

### 10.4 CSS 动画系统

所有动画使用纯 CSS 实现（零 JS 动画库依赖），通过 CSS 变量控制时长：

| 动画类 | 用途 |
|--------|------|
| `.view-enter` | 模式切换时整个视图入场（fadeIn + translateY） |
| `.step-forward` / `.step-backward` | Full Workflow 步骤前进/后退（slideX） |
| `.card-animate` + `.card-delay-N` | 卡片入场交错 |
| `.toast-enter` / `.toast--exiting` | Toast 滑入/滑出 |
| `.modalBackdrop--animated` / `.modalPanel--animated` | 模态框 fadeIn + scaleIn |

遵循 `@media (prefers-reduced-motion: reduce)` 将所有 duration 置 0。

### 10.5 状态管理

`app.jsx` 使用 `useReducer` 管理全局状态，关键 action：

| Action | 说明 |
|--------|------|
| `SET_MODE` | 切换 mode（landing/full/quick），重置 wizard stepIndex |
| `SET_STEP` | 设置 stepIndex（0-2，3 步） |
| `SET_TOAST_EXITING` | 标记 toast 为退出中（触发退出动画） |
| `RESET_FOR_NEW_COMPOSE` | 重置到 landing 模式 |
| `OPEN/CLOSE_POST_LOAD_CHOOSER` | 控制工作流选择模态框 |