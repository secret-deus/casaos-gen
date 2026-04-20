"""Stage 1 pipeline that fills CasaOS metadata using decomposed LLM prompts."""
from __future__ import annotations

import copy
import json
import logging
import time
from typing import Any, Optional

from .constants import (
    LLM_STAGE1_MAX_ATTEMPTS,
    LLM_STAGE1_RETRY_BASE_DELAY_SECONDS,
    OPENAI_MAX_RETRIES,
    OPENAI_REQUEST_TIMEOUT_SECONDS,
)
from .lmstudio_client import build_llm_client
from .models import CasaOSMeta

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional dependency during tests
    OpenAI = None

logger = logging.getLogger(__name__)


def _custom_instruction_block(custom_prompt: Optional[str]) -> str:
    custom = (custom_prompt or "").strip()
    if not custom:
        return ""
    return f"\nAdditional user instructions:\n{custom}\n"


def _is_generated_service_description(kind: str, container: str, description: str) -> bool:
    text = str(description or "").strip()
    target = str(container or "").strip()
    if not text or not target:
        return False
    expected = {
        "env": f"Environment variable {target}",
        "port": f"Port {target}",
        "volume": f"Volume {target}",
    }.get(kind)
    return text == expected


def _is_generated_app_tagline(title: str, tagline: str) -> bool:
    clean_title = str(title or "").strip()
    clean_tagline = str(tagline or "").strip()
    return bool(clean_title) and clean_tagline == f"{clean_title} on CasaOS"


def _is_generated_app_description(title: str, description: str) -> bool:
    clean_title = str(title or "").strip()
    clean_description = str(description or "").strip()
    if not clean_title or not clean_description:
        return False
    expected = (
        f"{clean_title} is a self-hosted application stack deployed via Docker Compose.\n\n"
        "Key Features:\n"
        "- Runs multiple services as a single stack.\n"
        "- Supports persistent storage and environment configuration.\n"
        "- Ready to be imported and managed in CasaOS.\n"
    ).strip()
    return clean_description == expected


def _strip_generated_placeholders(structure: CasaOSMeta) -> tuple[CasaOSMeta, int]:
    """Clear parser/template placeholder text so Stage 1 can regenerate it."""
    cleaned = copy.deepcopy(structure)
    stripped = 0

    if _is_generated_app_tagline(cleaned.app.title, cleaned.app.tagline):
        cleaned.app.tagline = ""
        stripped += 1
    if _is_generated_app_description(cleaned.app.title, cleaned.app.description):
        cleaned.app.description = ""
        stripped += 1

    for svc in cleaned.services.values():
        for env in svc.envs:
            if _is_generated_service_description("env", env.container, env.description):
                env.description = ""
                stripped += 1
        for port in svc.ports:
            if _is_generated_service_description("port", port.container, port.description):
                port.description = ""
                stripped += 1
        for vol in svc.volumes:
            if _is_generated_service_description("volume", vol.container, vol.description):
                vol.description = ""
                stripped += 1

    return cleaned, stripped


def build_stage1_prompt(structure: CasaOSMeta, custom_prompt: Optional[str] = None) -> str:
    """Legacy full-structure prompt kept for backward compatibility and tests."""
    structure_json = structure.model_dump()
    custom_block = ""
    if (custom_prompt or "").strip():
        custom_block = f"""

4. Additional user instructions:
   - Follow these instructions with higher priority than the default guidelines above
     when they do not conflict with the non-negotiable rules above.
{_custom_instruction_block(custom_prompt)}
"""
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

2. Non-negotiable rules:
   - DO NOT add new keys
   - DO NOT remove keys
   - DO NOT rename keys
   - DO NOT reorder anything
   - DO NOT output YAML
   - DO NOT wrap the response in Markdown code fences
   - Return ONLY valid JSON (no text outside the JSON)

3. Description guidelines:
   - Keep descriptions concise, professional, and accurate.
   - For ports: describe the function (e.g., "Main web interface port").
   - For environment variables: explain their purpose.
   - For volumes: describe the stored data.
   - app.tagline: short and catchy (<= 90 characters).
   - app.description MUST follow this structure (Markdown is allowed inside the string):
     - Paragraph 1: what the app is and who it's for.
     - Paragraph 2: core capabilities and typical use cases.
     - Paragraph 3: self-hosting/CasaOS deployment notes.
     - Blank line.
     - "**Key Features:**" followed by 3-6 bullet points (each line starts with "- ").
     - Blank line.
     - "**Learn More:**" followed by 2-4 bullet points with Markdown links (e.g. "- [Official Website](https://...)").
       Use official/verified URLs when confident; otherwise use placeholders like "<official_website>" and "<github_repo>".
{custom_block}

Here is the structure to fill:

{json.dumps(structure_json, indent=2)}

Return ONLY the completed JSON with no commentary.
""".strip()


def _build_app_field_prompt(meta: CasaOSMeta, field: str, custom_prompt: Optional[str] = None) -> str:
    app = meta.app
    context = {
        "title": app.title,
        "category": app.category,
        "author": app.author,
        "main": app.main,
        "port_map": app.port_map,
        "services": list(meta.services.keys()),
    }
    field_guidance = {
        "title": 'Generate a concise, user-facing app title. Return JSON: {"title":"..."}.',
        "tagline": 'Generate a short catchy tagline (<= 90 chars). Return JSON: {"tagline":"..."}.',
    }[field]
    return (
        "You generate CasaOS metadata in English.\n"
        f"Fill only the app.{field} field.\n"
        f"{field_guidance}\n"
        "Do not return Markdown fences or commentary.\n"
        f"App context:\n{json.dumps(context, ensure_ascii=False, indent=2)}\n"
        f"{_custom_instruction_block(custom_prompt)}"
    ).strip()


def _build_app_description_section_prompt(
    meta: CasaOSMeta,
    section: str,
    custom_prompt: Optional[str] = None,
) -> str:
    app = meta.app
    service_names = list(meta.services.keys())
    service_context = {
        svc_name: {
            "envs": [item.container for item in svc.envs][:8],
            "ports": [item.container for item in svc.ports][:8],
            "volumes": [item.container for item in svc.volumes][:8],
        }
        for svc_name, svc in list(meta.services.items())[:6]
    }
    context = {
        "title": app.title,
        "category": app.category,
        "author": app.author,
        "main": app.main,
        "port_map": app.port_map,
        "services": service_names,
        "service_context": service_context,
    }
    guidance = {
        "paragraph_1": (
            'Fill only the app.description paragraph 1 section. '
            'Return JSON: {"paragraph":"..."}. '
            "Describe what the app is and who it is for in 1-2 sentences."
        ),
        "paragraph_2": (
            'Fill only the app.description paragraph 2 section. '
            'Return JSON: {"paragraph":"..."}. '
            "Describe core capabilities and typical use cases in 1-2 sentences."
        ),
        "paragraph_3": (
            'Fill only the app.description paragraph 3 section. '
            'Return JSON: {"paragraph":"..."}. '
            "Describe self-hosting or CasaOS deployment notes in 1-2 sentences."
        ),
        "key_features": (
            'Fill only the app.description key features section. '
            'Return JSON: {"items":["...", "..."]}. '
            "Generate 3-6 concise feature bullet texts without leading '- '."
        ),
        "learn_more": (
            'Fill only the app.description learn more section. '
            'Return JSON: {"items":["...", "..."]}. '
            "Generate 2-4 Markdown link bullet texts without leading '- '. "
            "Use official links when confident, otherwise placeholders like "
            '"[Official Website](<official_website>)".'
        ),
    }[section]
    return (
        "You generate CasaOS metadata in English.\n"
        f"{guidance}\n"
        "Keep it accurate, concise, and professional.\n"
        "Do not return Markdown fences or commentary.\n"
        f"App context:\n{json.dumps(context, ensure_ascii=False, indent=2)}\n"
        f"{_custom_instruction_block(custom_prompt)}"
    ).strip()


def _build_service_field_prompt(
    meta: CasaOSMeta,
    service_name: str,
    kind: str,
    container: str,
    custom_prompt: Optional[str] = None,
) -> str:
    svc = meta.services.get(service_name)
    service_context = {
        "app_title": meta.app.title,
        "service": service_name,
        "main_service": meta.app.main,
        "category": meta.app.category,
        "known_envs": [item.container for item in (svc.envs if svc else [])][:12],
        "known_ports": [item.container for item in (svc.ports if svc else [])][:12],
        "known_volumes": [item.container for item in (svc.volumes if svc else [])][:12],
    }
    kind_guidance = {
        "env": (
            f'Write a concise English description for environment variable "{container}". '
            'Explain purpose, not value. Return JSON: {"description":"..."}.'
        ),
        "port": (
            f'Write a concise English description for container port "{container}". '
            'Describe the function of the port. Return JSON: {"description":"..."}.'
        ),
        "volume": (
            f'Write a concise English description for container path "{container}". '
            'Describe what data is stored there. Return JSON: {"description":"..."}.'
        ),
    }[kind]
    return (
        "You generate CasaOS metadata in English.\n"
        f"{kind_guidance}\n"
        "Keep it short, accurate, and professional.\n"
        "Do not return Markdown fences or commentary.\n"
        f"Service context:\n{json.dumps(service_context, ensure_ascii=False, indent=2)}\n"
        f"{_custom_instruction_block(custom_prompt)}"
    ).strip()


def _parse_json_response(content: str) -> dict[str, Any]:
    from .utils import parse_llm_json

    return parse_llm_json(content)


def _coerce_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            out.append(text.lstrip("- ").strip())
    return out


def _assemble_app_description(
    paragraph_1: str,
    paragraph_2: str,
    paragraph_3: str,
    key_features: list[str],
    learn_more: list[str],
) -> str:
    sections: list[str] = []
    for paragraph in (paragraph_1, paragraph_2, paragraph_3):
        text = str(paragraph or "").strip()
        if text:
            sections.append(text)
    if key_features:
        bullets = "\n".join(f"- {item}" for item in key_features)
        sections.append(f"**Key Features:**\n{bullets}")
    if learn_more:
        bullets = "\n".join(f"- {item}" for item in learn_more)
        sections.append(f"**Learn More:**\n{bullets}")
    return "\n\n".join(sections).strip()


def _request_json_payload(
    client: object,
    *,
    model: str,
    prompt: str,
    temperature: float,
    max_tokens: Optional[int] = None,
) -> dict[str, Any]:
    safe_temperature = max(0.0, min(float(temperature), 0.3))
    last_error: Optional[Exception] = None

    for attempt in range(1, LLM_STAGE1_MAX_ATTEMPTS + 1):
        try:
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": safe_temperature,
            }
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens
            try:
                response = client.chat.completions.create(**kwargs)
            except TypeError as exc:
                if "max_tokens" not in str(exc):
                    raise
                kwargs.pop("max_tokens", None)
                response = client.chat.completions.create(**kwargs)

            content = response.choices[0].message.content or ""
            logger.debug("Stage 1 field raw response: %s", content[:300])
            return _parse_json_response(content)
        except Exception as exc:  # pragma: no cover
            last_error = exc
            if attempt >= LLM_STAGE1_MAX_ATTEMPTS:
                raise
            delay = LLM_STAGE1_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
            logger.warning(
                "Stage 1 field request failed on attempt %d/%d; retrying in %.1fs: %s",
                attempt,
                LLM_STAGE1_MAX_ATTEMPTS,
                delay,
                exc,
            )
            if delay > 0:
                time.sleep(delay)

    if last_error is not None:
        raise last_error
    raise RuntimeError("Stage 1 field request failed without a response.")


def _fill_missing_app_fields_with_llm(
    meta: CasaOSMeta,
    *,
    model: str,
    temperature: float,
    client: object,
    custom_prompt: Optional[str],
) -> None:
    field_limits = {"title": 64, "tagline": 96}
    for field in ("title", "tagline"):
        current = str(getattr(meta.app, field) or "").strip()
        if current:
            continue
        prompt = _build_app_field_prompt(meta, field, custom_prompt=custom_prompt)
        payload = _request_json_payload(
            client,
            model=model,
            prompt=prompt,
            temperature=temperature,
            max_tokens=field_limits[field],
        )
        candidate = str(payload.get(field) or "").strip()
        if candidate:
            setattr(meta.app, field, candidate)

    if str(meta.app.description or "").strip():
        return

    section_specs = (
        ("paragraph_1", "paragraph", 160),
        ("paragraph_2", "paragraph", 160),
        ("paragraph_3", "paragraph", 160),
        ("key_features", "items", 192),
        ("learn_more", "items", 192),
    )
    description_parts: dict[str, Any] = {}
    for section, key, max_tokens in section_specs:
        prompt = _build_app_description_section_prompt(meta, section, custom_prompt=custom_prompt)
        payload = _request_json_payload(
            client,
            model=model,
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        description_parts[section] = payload.get(key)

    candidate = _assemble_app_description(
        str(description_parts.get("paragraph_1") or "").strip(),
        str(description_parts.get("paragraph_2") or "").strip(),
        str(description_parts.get("paragraph_3") or "").strip(),
        _coerce_string_list(description_parts.get("key_features")),
        _coerce_string_list(description_parts.get("learn_more")),
    )
    if candidate:
        meta.app.description = candidate


def _fill_missing_service_fields_with_llm(
    meta: CasaOSMeta,
    *,
    model: str,
    temperature: float,
    client: object,
    custom_prompt: Optional[str],
) -> None:
    for service_name, svc in meta.services.items():
        for kind, items in (("env", svc.envs), ("port", svc.ports), ("volume", svc.volumes)):
            for item in items:
                if str(item.description or "").strip():
                    continue
                prompt = _build_service_field_prompt(
                    meta,
                    service_name,
                    kind,
                    item.container,
                    custom_prompt=custom_prompt,
                )
                payload = _request_json_payload(
                    client,
                    model=model,
                    prompt=prompt,
                    temperature=temperature,
                    max_tokens=128,
                )
                candidate = str(payload.get("description") or "").strip()
                if candidate:
                    item.description = candidate


def run_stage1_llm(
    structure: CasaOSMeta,
    model: str = "gpt-4.1-mini",
    temperature: float = 0.2,
    client: Optional[object] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    only_fill_empty: bool = False,
    prompt_instructions: Optional[str] = None,
) -> CasaOSMeta:
    """Fill Stage 1 metadata via decomposed field-level LLM requests."""
    meta = copy.deepcopy(structure)
    fallback = copy.deepcopy(meta)
    meta, stripped_placeholders = _strip_generated_placeholders(meta)
    if stripped_placeholders:
        logger.info("Stage 1 cleared %d generated placeholder descriptions before LLM fill", stripped_placeholders)

    if client is None:
        if OpenAI is None:
            from .exceptions import LLMUnavailableError

            raise LLMUnavailableError(
                "openai package is not available. Install it or provide a custom client."
            )
        client = build_llm_client(
            openai_cls=OpenAI,
            api_key=api_key,
            base_url=base_url,
            timeout=OPENAI_REQUEST_TIMEOUT_SECONDS,
            max_retries=OPENAI_MAX_RETRIES,
        )

    if only_fill_empty:
        logger.info("Incremental fill mode: preserving existing values and filling blanks only.")

    logger.info("Calling LLM model %s for CasaOS metadata (decomposed field mode)", model)
    _fill_missing_app_fields_with_llm(
        meta,
        model=model,
        temperature=temperature,
        client=client,
        custom_prompt=prompt_instructions,
    )
    _fill_missing_service_fields_with_llm(
        meta,
        model=model,
        temperature=temperature,
        client=client,
        custom_prompt=prompt_instructions,
    )
    _fill_missing_app_text(meta, fallback)
    _fill_missing_service_text(meta, fallback)
    return meta


def _fill_missing_app_text(meta: CasaOSMeta, fallback: CasaOSMeta) -> None:
    """Ensure app title/tagline/description are non-empty after Stage 1."""
    if not meta.app.title.strip():
        meta.app.title = fallback.app.title
    if not meta.app.tagline.strip():
        meta.app.tagline = fallback.app.tagline
    if not meta.app.description.strip():
        meta.app.description = fallback.app.description


def _fill_missing_service_text(meta: CasaOSMeta, fallback: CasaOSMeta) -> None:
    """Restore deterministic service descriptions when LLM leaves blanks."""
    for svc_name, fallback_svc in fallback.services.items():
        svc = meta.services.get(svc_name)
        if svc is None:
            continue

        fallback_envs = {item.container: item.description for item in fallback_svc.envs}
        for item in svc.envs:
            if not item.description.strip():
                item.description = fallback_envs.get(item.container, item.description)

        fallback_ports = {item.container: item.description for item in fallback_svc.ports}
        for item in svc.ports:
            if not item.description.strip():
                item.description = fallback_ports.get(item.container, item.description)

        fallback_volumes = {item.container: item.description for item in fallback_svc.volumes}
        for item in svc.volumes:
            if not item.description.strip():
                item.description = fallback_volumes.get(item.container, item.description)


# Refine functions live in refine_mode.py (single source of truth).
# Re-export for backward compatibility.
from .refine_mode import build_refine_prompt, refine_user_inputs  # noqa: F401
