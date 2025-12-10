"""Stage 1 pipeline that asks an LLM to fill CasaOS metadata descriptions."""
from __future__ import annotations

import json
import logging
from typing import Optional

from .models import CasaOSMeta

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional dependency during tests
    OpenAI = None

logger = logging.getLogger(__name__)


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
) -> CasaOSMeta:
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
    return meta


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

