"""Stage 1 pipeline that asks an LLM to fill CasaOS metadata descriptions."""
from __future__ import annotations

import copy
import json
import logging
from typing import Optional

from .models import CasaOSMeta

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional dependency during tests
    OpenAI = None

logger = logging.getLogger(__name__)


def _filter_empty_fields(structure: CasaOSMeta) -> tuple[CasaOSMeta, dict]:
    """
    过滤出需要填充的空白字段，返回精简结构和原始映射

    Args:
        structure: 完整元数据结构

    Returns:
        (精简结构, 原始字段映射)
    """
    # 深拷贝以避免修改原始数据
    filtered = copy.deepcopy(structure)
    original_mapping = {"app": {}, "services": {}}

    # 检查 app 级别
    app = filtered.app
    if app.title.strip():
        original_mapping["app"]["title"] = app.title
    if app.tagline.strip():
        original_mapping["app"]["tagline"] = app.tagline
    if app.description.strip():
        original_mapping["app"]["description"] = app.description

    # 检查服务级别
    for svc_name, svc in filtered.services.items():
        original_mapping["services"][svc_name] = {"ports": {}, "envs": {}, "volumes": {}}

        for port in svc.ports:
            if port.description.strip():
                original_mapping["services"][svc_name]["ports"][port.container] = port.description

        for env in svc.envs:
            if env.description.strip():
                original_mapping["services"][svc_name]["envs"][env.container] = env.description

        for vol in svc.volumes:
            if vol.description.strip():
                original_mapping["services"][svc_name]["volumes"][vol.container] = vol.description

    return filtered, original_mapping


def _restore_existing_fields(meta: CasaOSMeta, original_mapping: dict) -> CasaOSMeta:
    """
    将已有的字段值恢复到元数据中

    Args:
        meta: LLM 返回的元数据
        original_mapping: 原始字段映射

    Returns:
        恢复后的元数据
    """
    # 恢复 app 级别
    app_map = original_mapping.get("app", {})
    if "title" in app_map:
        meta.app.title = app_map["title"]
    if "tagline" in app_map:
        meta.app.tagline = app_map["tagline"]
    if "description" in app_map:
        meta.app.description = app_map["description"]

    # 恢复服务级别
    services_map = original_mapping.get("services", {})
    for svc_name, svc_map in services_map.items():
        if svc_name not in meta.services:
            continue

        svc = meta.services[svc_name]

        # 恢复端口
        port_map = {p.container: p for p in svc.ports}
        for container, desc in svc_map.get("ports", {}).items():
            if container in port_map:
                port_map[container].description = desc

        # 恢复环境变量
        env_map = {e.container: e for e in svc.envs}
        for container, desc in svc_map.get("envs", {}).items():
            if container in env_map:
                env_map[container].description = desc

        # 恢复存储卷
        vol_map = {v.container: v for v in svc.volumes}
        for container, desc in svc_map.get("volumes", {}).items():
            if container in vol_map:
                vol_map[container].description = desc

    return meta


def build_stage1_prompt(structure: CasaOSMeta) -> str:
    structure_json = structure.model_dump()
    return f"""
You are an expert in generating metadata for CasaOS applications.

I will give you a JSON object representing the structural metadata extracted from a docker-compose.yml file.
The structure is correct and MUST NOT be modified.

Your task:
1. Fill ONLY the following text fields in English:
   - app.title
   - app.tagline
   - app.description
   - services[*].envs[*].description
   - services[*].ports[*].description
   - services[*].volumes[*].description

   If a field already contains non-empty text, keep it unchanged and only fill missing fields.

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
   - For volumes: describe the stored data.
   - app.description must include a short introduction followed by a "Key Features:" list with bullet-style sentences.

Here is the structure to fill:

{json.dumps(structure_json, indent=2)}

Return ONLY the completed JSON with no commentary.
""".strip()


def run_stage1_llm(
    structure: CasaOSMeta,
    model: str = "gpt-4.1-mini",
    temperature: float = 0.2,
    client: Optional[object] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    only_fill_empty: bool = False,
) -> CasaOSMeta:
    """
    调用 LLM 填充 CasaOS 元数据描述

    Args:
        structure: 元数据结构
        model: LLM 模型名称
        temperature: 采样温度
        client: 可选的 OpenAI 客户端实例
        api_key: OpenAI API 密钥
        base_url: OpenAI API 基础 URL
        only_fill_empty: 如果为 True，只填充空白字段，保留已有内容

    Returns:
        填充后的元数据
    """
    if client is None:
        if OpenAI is None:
            raise RuntimeError(
                "openai package is not available. Install it or provide a custom client."
            )
        client_kwargs = {}
        if api_key:
            client_kwargs["api_key"] = api_key
        if base_url:
            client_kwargs["base_url"] = base_url
        client = OpenAI(**client_kwargs)

    # 如果只填充空白字段，先记录已有内容
    original_mapping = None
    if only_fill_empty:
        structure, original_mapping = _filter_empty_fields(structure)
        logger.info("增量填充模式：保留已有字段，只填充空白字段")

    prompt = build_stage1_prompt(structure)
    logger.info("Calling LLM model %s for CasaOS metadata", model)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    content = response.choices[0].message.content or ""
    logger.debug("LLM raw response: %s", content[:400])
    data = _parse_json_response(content)
    meta = CasaOSMeta.model_validate(data)
    _fill_missing_app_text(meta, structure)

    # 如果是增量模式，恢复已有字段
    if only_fill_empty and original_mapping:
        meta = _restore_existing_fields(meta, original_mapping)
        logger.info("已恢复原有字段内容")

    return meta


def _fill_missing_app_text(meta: CasaOSMeta, fallback: CasaOSMeta) -> None:
    """Ensure app title/tagline/description are non-empty after Stage 1.

    Some models may fail to fill fields; we keep deterministic defaults from the
    skeleton (derived from compose) to avoid empty multi-language output.
    """
    if not meta.app.title.strip():
        meta.app.title = fallback.app.title
    if not meta.app.tagline.strip():
        meta.app.tagline = fallback.app.tagline
    if not meta.app.description.strip():
        meta.app.description = fallback.app.description


def _parse_json_response(content: str) -> dict:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()

    if not cleaned.startswith("{"):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1:
            cleaned = cleaned[start : end + 1]

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive logging
        logger.error("Failed to parse LLM JSON: %s", exc)
        raise


def build_refine_prompt(structure: CasaOSMeta) -> str:
    """
    构建润色模式的 prompt
    
    润色模式：保持用户输入的核心含义，只改进表达
    """
    structure_json = structure.model_dump()
    return f"""
You are an expert in refining technical documentation for CasaOS applications.

I will give you a JSON object with user-provided descriptions that need refinement.
Your task is to improve the clarity and professionalism of the text while preserving the original meaning.

Guidelines:
1. PRESERVE the core meaning and intent of each description
2. Improve clarity, grammar, and professionalism
3. Keep descriptions concise (similar length to original)
4. Use technical terminology appropriately
5. Output in English only
6. DO NOT add new information not implied by the original text
7. DO NOT change the JSON structure

Fields to refine (only if non-empty):
- app.title, app.tagline, app.description
- services[*].envs[*].description
- services[*].ports[*].description
- services[*].volumes[*].description

Here is the structure to refine:

{json.dumps(structure_json, indent=2)}

Return ONLY the refined JSON with no commentary.
""".strip()


def refine_user_inputs(
    structure: CasaOSMeta,
    model: str = "gpt-4.1-mini",
    temperature: float = 0.2,
    client: Optional[object] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> CasaOSMeta:
    """
    润色用户输入的描述（保持原意）
    
    Args:
        structure: 包含用户输入的元数据
        model: LLM 模型名称
        temperature: 采样温度
        client: 可选的 OpenAI 客户端实例
        api_key: OpenAI API 密钥
        base_url: OpenAI API 基础 URL
    
    Returns:
        润色后的元数据
    """
    if client is None:
        if OpenAI is None:
            raise RuntimeError(
                "openai package is not available. Install it or provide a custom client."
            )
        client_kwargs = {}
        if api_key:
            client_kwargs["api_key"] = api_key
        if base_url:
            client_kwargs["base_url"] = base_url
        client = OpenAI(**client_kwargs)
    
    prompt = build_refine_prompt(structure)
    logger.info("Calling LLM model %s for refining user inputs", model)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    content = response.choices[0].message.content or ""
    logger.debug("LLM refine response: %s", content[:400])
    data = _parse_json_response(content)
    meta = CasaOSMeta.model_validate(data)
    
    return meta
