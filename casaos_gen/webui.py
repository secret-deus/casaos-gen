"""FastAPI-based Web UI for CasaOS compose generation and editing."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import uvicorn
import yaml
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel

from .i18n import DEFAULT_LANGUAGES, load_translation_map
from .llm_stage1 import run_stage1_llm
from .main import stage_two_from_meta
from .models import CasaOSMeta
from .parser import build_casaos_meta

logger = logging.getLogger(__name__)


@dataclass
class WebState:
    compose_data: Optional[dict] = None
    compose_text: str = ""
    meta: Optional[CasaOSMeta] = None
    languages: List[str] = field(default_factory=lambda: list(DEFAULT_LANGUAGES))
    translation_map: Dict[str, Dict[str, str]] = field(default_factory=load_translation_map)


STATE = WebState()
app = FastAPI(title="CasaOS Compose Generator UI")


def _parse_compose_text(text: str) -> dict:
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError("Compose content must be a YAML mapping.")
    return data


def _require_meta() -> CasaOSMeta:
    if STATE.meta is None or STATE.compose_data is None:
        raise HTTPException(status_code=400, detail="No compose metadata is loaded yet.")
    return STATE.meta


def _parse_service_target(target: str) -> Tuple[str, str, str]:
    parts = target.split(":")
    if len(parts) < 4 or parts[0] != "service":
        raise HTTPException(
            status_code=400,
            detail="Target must look like service:NAME:type:key (e.g. service:web:port:8080)",
        )
    service_name = parts[1]
    field_type = parts[2]
    identifier = ":".join(parts[3:])
    return service_name, field_type, identifier


def _propagate_translation(text: str) -> None:
    if not text:
        return
    entry = STATE.translation_map.setdefault(text, {})
    for lang in STATE.languages:
        if lang == "en_US":
            continue
        entry[lang] = text


def _ensure_stage2_structure(require_meta: bool = False) -> None:
    if STATE.compose_data is None:
        raise HTTPException(status_code=400, detail="No compose file loaded.")
    if STATE.compose_data.get("x-casaos"):
        return
    if STATE.meta is None:
        if require_meta:
            raise HTTPException(status_code=400, detail="Stage 1 metadata unavailable. Run Stage 1 first.")
        return
    STATE.compose_data = stage_two_from_meta(
        STATE.compose_data,
        STATE.meta,
        languages=STATE.languages,
        translation_map_override=STATE.translation_map,
    )


class FieldUpdate(BaseModel):
    target: str
    value: str
    propagate_all_languages: bool = False


class Stage2MultiUpdate(BaseModel):
    target: str
    value: str


class Stage2SingleUpdate(BaseModel):
    target: str
    value: str


def _update_meta_field(meta: CasaOSMeta, payload: FieldUpdate) -> None:
    if payload.target.startswith("app."):
        field = payload.target.split(".", 1)[1]
        if not hasattr(meta.app, field):
            raise HTTPException(status_code=400, detail=f"Unknown app field: {field}")
        setattr(meta.app, field, payload.value)
        return

    service_name, field_type, identifier = _parse_service_target(payload.target)
    service_meta = meta.services.get(service_name)
    if not service_meta:
        raise HTTPException(status_code=404, detail=f"Service {service_name} not found in metadata.")

    collection_map = {
        "env": service_meta.envs,
        "port": service_meta.ports,
        "volume": service_meta.volumes,
    }
    items = collection_map.get(field_type)
    if items is None:
        raise HTTPException(status_code=400, detail=f"Unknown field type: {field_type}")

    target_item = next((item for item in items if item.container == identifier), None)
    if target_item is None:
        raise HTTPException(
            status_code=404, detail=f"{field_type} entry {identifier} not found for service {service_name}."
        )
    target_item.description = payload.value


def _update_stage2_multi_field(payload: Stage2MultiUpdate) -> None:
    _ensure_stage2_structure(require_meta=True)
    compose = STATE.compose_data or {}

    if payload.target.startswith("app."):
        field_path = payload.target.split(".", 1)[1]
        block = compose.setdefault("x-casaos", {})
        scope = block
        parts = field_path.split(".")
        for key in parts[:-1]:
            scope = scope.setdefault(key, {})
        multilang = scope.setdefault(parts[-1], {})
        if not isinstance(multilang, dict):
            multilang = {}
            scope[parts[-1]] = multilang
        for lang in STATE.languages:
            multilang[lang] = payload.value
        return

    service_name, field_type, identifier = _parse_service_target(payload.target)
    services = compose.get("services") or {}
    service = services.get(service_name)
    if not service:
        raise HTTPException(status_code=404, detail=f"Service {service_name} not present in compose.")

    plural_map = {"env": "envs", "port": "ports", "volume": "volumes"}
    list_name = plural_map.get(field_type)
    if list_name is None:
        raise HTTPException(status_code=400, detail=f"Unknown field type: {field_type}")

    x_block = service.setdefault("x-casaos", {})
    items = x_block.setdefault(list_name, [])
    target_item = None
    for entry in items:
        if entry.get("container") == identifier:
            target_item = entry
            break
    if target_item is None:
        target_item = {"container": identifier, "description": {}}
        items.append(target_item)
    desc = target_item.setdefault("description", {})
    if not isinstance(desc, dict):
        desc = {}
        target_item["description"] = desc
    for lang in STATE.languages:
        desc[lang] = payload.value


def _update_stage2_single_field(payload: Stage2SingleUpdate) -> None:
    _ensure_stage2_structure(require_meta=True)
    compose = STATE.compose_data or {}

    if payload.target.startswith("app."):
        field_path = payload.target.split(".", 1)[1]
        block = compose.setdefault("x-casaos", {})
        scope = block
        parts = field_path.split(".")
        for key in parts[:-1]:
            scope = scope.setdefault(key, {})
        scope[parts[-1]] = payload.value
        return

    parts = payload.target.split(":")
    if len(parts) < 3 or parts[0] != "service":
        raise HTTPException(
            status_code=400,
            detail="Target must look like app.xxx or service:NAME:field for single-language editing.",
        )
    service_name = parts[1]
    field_path = ":".join(parts[2:])
    services = compose.get("services") or {}
    service = services.get(service_name)
    if not service:
        raise HTTPException(status_code=404, detail=f"Service {service_name} not present in compose.")
    block = service.setdefault("x-casaos", {})
    scope = block
    fragments = field_path.split(".")
    for key in fragments[:-1]:
        scope = scope.setdefault(key, {})
    scope[fragments[-1]] = payload.value


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(content=HTML_TEMPLATE)


@app.get("/api/state")
async def get_state() -> dict:
    return {
        "languages": STATE.languages,
        "has_meta": STATE.meta is not None,
        "has_stage2": bool(STATE.compose_data and STATE.compose_data.get("x-casaos")),
        "meta": STATE.meta.model_dump() if STATE.meta else None,
    }


@app.post("/api/upload")
async def upload_compose(
    file: UploadFile = File(...),
    run_stage1: bool = Form(False),
    model: str = Form("gpt-4.1-mini"),
    temperature: float = Form(0.2),
    llm_base_url: Optional[str] = Form(None),
    llm_api_key: Optional[str] = Form(None),
) -> dict:
    content = await file.read()
    try:
        text = content.decode("utf-8")
        compose_data = _parse_compose_text(text)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to parse compose file: {exc}") from exc

    skeleton = build_casaos_meta(compose_data)
    meta = skeleton
    if run_stage1:
        meta = run_stage1_llm(
            skeleton,
            model=model,
            temperature=temperature,
            api_key=llm_api_key,
            base_url=llm_base_url,
        )

    STATE.compose_data = compose_data
    STATE.compose_text = text
    STATE.meta = meta
    return {"message": "Compose uploaded.", "meta": meta.model_dump()}


@app.post("/api/meta/update")
async def update_meta_field(payload: FieldUpdate) -> dict:
    meta = _require_meta()
    _update_meta_field(meta, payload)
    if payload.propagate_all_languages:
        _propagate_translation(payload.value)
    return {"status": "ok", "meta": meta.model_dump()}


@app.post("/api/stage2/update-multi")
async def update_stage2_multi_field(payload: Stage2MultiUpdate) -> dict:
    _update_stage2_multi_field(payload)
    return {"status": "ok", "compose": STATE.compose_data}


@app.post("/api/stage2/update-single")
async def update_stage2_single_field(payload: Stage2SingleUpdate) -> dict:
    _update_stage2_single_field(payload)
    return {"status": "ok", "compose": STATE.compose_data}


@app.post("/api/export", response_class=PlainTextResponse)
async def export_compose() -> PlainTextResponse:
    if STATE.compose_data is None:
        raise HTTPException(status_code=400, detail="No compose file loaded.")
    _ensure_stage2_structure()
    compose = STATE.compose_data
    if not compose.get("x-casaos"):
        raise HTTPException(status_code=400, detail="Stage 2 data unavailable. Run Stage 1 first.")
    yaml_text = yaml.safe_dump(compose, sort_keys=False)
    return PlainTextResponse(yaml_text, media_type="text/yaml")


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>CasaOS Compose Generator</title>
  <style>
    :root {
      font-family: "Segoe UI", system-ui, Avenir, Helvetica, Arial, sans-serif;
      background: #f5f7fb;
      color: #1c1c1c;
    }
    body {
      margin: 0;
      padding: 2rem;
      background: #f5f7fb;
    }
    h1 { margin-bottom: 1.5rem; }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 1.5rem;
    }
    .card {
      background: #fff;
      border-radius: 16px;
      box-shadow: 0 12px 30px rgba(15, 23, 42, 0.08);
      padding: 1.5rem;
      display: flex;
      flex-direction: column;
      gap: 0.75rem;
    }
    label {
      font-size: 0.9rem;
      font-weight: 600;
      color: #475467;
    }
    input[type="text"],
    input[type="password"],
    input[type="number"],
    textarea,
    select {
      width: 100%;
      border: 1px solid #d0d5dd;
      border-radius: 10px;
      padding: 0.6rem 0.8rem;
      font-size: 0.95rem;
      font-family: inherit;
    }
    textarea {
      min-height: 160px;
      resize: vertical;
    }
    button {
      border: none;
      border-radius: 10px;
      padding: 0.65rem 1rem;
      font-size: 0.95rem;
      font-weight: 600;
      color: #fff;
      background: linear-gradient(135deg, #2563eb, #9333ea);
      cursor: pointer;
      transition: opacity 0.2s ease;
    }
    button:hover { opacity: 0.9; }
    .card small {
      color: #6b7280;
      line-height: 1.4;
    }
    .checkbox-row {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      font-size: 0.9rem;
      color: #475467;
    }
    pre {
      background: #0f172a;
      color: #e2e8f0;
      border-radius: 12px;
      padding: 1rem;
      max-height: 280px;
      overflow: auto;
      font-size: 0.85rem;
    }
  </style>
</head>
<body>
  <div id="root"></div>
  <script crossorigin src="https://unpkg.com/react@18/umd/react.development.js"></script>
  <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
  <script src="https://unpkg.com/babel-standalone@6/babel.min.js"></script>
  <script type="text/babel">
    const { useState, useEffect, useRef } = React;
    const LANG_OPTIONS = ["de_DE","el_GR","en_GB","en_US","fr_FR","hr_HR","it_IT","ja_JP","ko_KR","nb_NO","pt_PT","ru_RU","sv_SE","tr_TR","zh_CN"];

    const Card = ({ title, children, intro }) => (
      <section className="card">
        <div>
          <h2 style={{ margin: 0 }}>{title}</h2>
          {intro && <small>{intro}</small>}
        </div>
        {children}
      </section>
    );

    const App = () => {
      const [state, setState] = useState({ languages: LANG_OPTIONS, has_meta: false, has_stage2: false, meta: null });
      const [target, setTarget] = useState("");
      const [value, setValue] = useState("");
      const [propagate, setPropagate] = useState(false);
      const [stage2SingleTarget, setStage2SingleTarget] = useState("");
      const [stage2SingleValue, setStage2SingleValue] = useState("");
      const [stage2MultiTarget, setStage2MultiTarget] = useState("");
      const [stage2MultiValue, setStage2MultiValue] = useState("");
      const [exportOutput, setExportOutput] = useState("");
      const [runStage1, setRunStage1] = useState(false);
      const [model, setModel] = useState("gpt-4.1-mini");
      const [temperature, setTemperature] = useState(0.2);
      const [llmBaseUrl, setLlmBaseUrl] = useState("");
      const [llmApiKey, setLlmApiKey] = useState("");
      const [message, setMessage] = useState("");
      const fileRef = useRef(null);

      const setStatus = (text) => {
        setMessage(text);
        setTimeout(() => setMessage(""), 4000);
      };

      const refreshState = async () => {
        const response = await fetch("/api/state");
        const data = await response.json();
        setState(data);
      };

      useEffect(() => { refreshState(); }, []);

      const uploadCompose = async () => {
        if (!fileRef.current || !fileRef.current.files.length) {
          setStatus("Please choose a docker-compose file.");
          return;
        }
        const formData = new FormData();
        formData.append("file", fileRef.current.files[0]);
        formData.append("run_stage1", runStage1 ? "true" : "false");
        formData.append("model", model);
        formData.append("temperature", temperature);
        if (llmBaseUrl) formData.append("llm_base_url", llmBaseUrl);
        if (llmApiKey) formData.append("llm_api_key", llmApiKey);
        const response = await fetch("/api/upload", { method: "POST", body: formData });
        const data = await response.json();
        if (!response.ok) {
          setStatus(data.detail || "Upload failed");
          return;
        }
        setStatus(data.message || "Upload succeeded");
        refreshState();
      };

      const updateField = async () => {
        if (!target || !value) {
          setStatus("Target and Value are required.");
          return;
        }
        const response = await fetch("/api/meta/update", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ target, value, propagate_all_languages: propagate }),
        });
        const data = await response.json();
        if (!response.ok) {
          setStatus(data.detail || "Update failed");
          return;
        }
        setStatus("Stage 1 metadata updated.");
        setTarget("");
        setValue("");
        setPropagate(false);
        refreshState();
      };

      const updateStage2Single = async () => {
        if (!stage2SingleTarget || !stage2SingleValue) {
          setStatus("Single-language target and value are required.");
          return;
        }
        const response = await fetch("/api/stage2/update-single", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ target: stage2SingleTarget, value: stage2SingleValue }),
        });
        const data = await response.json();
        if (!response.ok) {
          setStatus(data.detail || "Single-language update failed");
          return;
        }
        setStatus("Single-language value saved.");
        setStage2SingleValue("");
        refreshState();
      };

      const updateStage2Multi = async () => {
        if (!stage2MultiTarget || !stage2MultiValue) {
          setStatus("Multi-language target and content are required.");
          return;
        }
        const response = await fetch("/api/stage2/update-multi", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ target: stage2MultiTarget, value: stage2MultiValue }),
        });
        const data = await response.json();
        if (!response.ok) {
          setStatus(data.detail || "Multi-language update failed");
          return;
        }
        setStatus("Multi-language value saved (applied to all locales).");
        setStage2MultiValue("");
        refreshState();
      };

      const exportCompose = async () => {
        const response = await fetch("/api/export", { method: "POST" });
        if (!response.ok) {
          const data = await response.json();
          setStatus(data.detail || "Export failed");
          return;
        }
        const text = await response.text();
        setExportOutput(text);
        setStatus("CasaOS YAML generated.");
      };

      return (
        <div>
          <h1>CasaOS Compose Generator Web UI</h1>
          {message && (
            <div style={{ marginBottom: "1rem", padding: "0.75rem 1rem", background: "#e0f2fe", borderRadius: "10px" }}>
              {message}
            </div>
          )}
          <div className="grid">
            <Card
              title="Upload Compose + LLM"
              intro="Upload docker-compose.yml, optionally run Stage 1, and configure a custom LLM endpoint."
            >
              <label>docker-compose file</label>
              <input ref={fileRef} type="file" accept=".yml,.yaml" />
              <div className="checkbox-row">
                <input type="checkbox" checked={runStage1} onChange={(e) => setRunStage1(e.target.checked)} />
                <span>Run Stage 1 (requires LLM)</span>
              </div>
              <label>LLM Base URL</label>
              <input type="text" placeholder="https://api.openai.com/v1" value={llmBaseUrl} onChange={(e) => setLlmBaseUrl(e.target.value)} />
              <label>LLM API Key</label>
              <input type="password" placeholder="sk-..." value={llmApiKey} onChange={(e) => setLlmApiKey(e.target.value)} />
              <label>Model</label>
              <input type="text" value={model} onChange={(e) => setModel(e.target.value)} />
              <label>Temperature</label>
              <input type="number" step="0.1" min="0" max="1" value={temperature} onChange={(e) => setTemperature(e.target.value)} />
              <button onClick={uploadCompose}>Upload &amp; Process</button>
            </Card>

            <Card
              title="Stage 1 Field Editing"
              intro="Targets: app.title / service:NAME:env:KEY / service:NAME:port:8080 / service:NAME:volume:/path"
            >
              <label>Target</label>
              <input type="text" value={target} placeholder="app.title" onChange={(e) => setTarget(e.target.value)} />
              <label>Value</label>
              <input type="text" value={value} onChange={(e) => setValue(e.target.value)} />
              <div className="checkbox-row">
                <input type="checkbox" checked={propagate} onChange={(e) => setPropagate(e.target.checked)} />
                <span>Copy to all languages (stores text in translation table)</span>
              </div>
              <button onClick={updateField}>Save Stage 1 Metadata</button>
            </Card>

            <Card
              title="Stage 2 单语言编辑"
              intro="Use this for fields without locale keys (e.g., category, author, scheme)."
            >
              <label>Target</label>
              <input type="text" value={stage2SingleTarget} placeholder="app.category or service:web:index" onChange={(e) => setStage2SingleTarget(e.target.value)} />
              <label>Value</label>
              <input type="text" value={stage2SingleValue} onChange={(e) => setStage2SingleValue(e.target.value)} />
              <small>Targets look like app.xxx or service:NAME:field</small>
              <button onClick={updateStage2Single}>Save Single-language Value</button>
            </Card>

            <Card
              title="Stage 2 多语言编辑"
              intro="Use this for locale dictionaries (title, description, tips, env/port descriptions). One edit copies to all languages."
            >
              <label>Target</label>
              <input type="text" value={stage2MultiTarget} placeholder="service:web:port:8080 or app.tips.before_install" onChange={(e) => setStage2MultiTarget(e.target.value)} />
              <label>Content</label>
              <textarea value={stage2MultiValue} onChange={(e) => setStage2MultiValue(e.target.value)} placeholder="Multi-line description will sync to all languages..." />
              <small>Examples: app.title / app.tips.before_install / service:web:env:TZ / service:web:volume:/data</small>
              <button onClick={updateStage2Multi}>Save Multi-language Value</button>
            </Card>

            <Card title="Export CasaOS YAML" intro="Generate Stage 2 output once metadata is ready.">
              <button onClick={exportCompose}>Generate YAML</button>
              <textarea value={exportOutput} onChange={(e) => setExportOutput(e.target.value)} placeholder="CasaOS YAML will appear here" />
            </Card>

            <Card title="Current State" intro="Shows languages, Stage 1 metadata, and Stage 2 readiness.">
              <button onClick={refreshState}>Refresh State</button>
              <pre>{JSON.stringify(state, null, 2)}</pre>
            </Card>
          </div>
        </div>
      );
    };

    const root = ReactDOM.createRoot(document.getElementById("root"));
    root.render(<App />);
  </script>
</body>
</html>
"""


def run(host: str = "127.0.0.1", port: int = 8001) -> None:
    """Launch the FastAPI web UI using uvicorn."""
    logger.info("Starting CasaOS web UI on %s:%s", host, port)
    uvicorn.run("casaos_gen.webui:app", host=host, port=port, reload=False)


if __name__ == "__main__":  # pragma: no cover
    run()
