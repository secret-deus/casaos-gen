"""AI refine mode for polishing user inputs while preserving meaning."""
from __future__ import annotations

import json
import logging
from typing import Optional

from .models import CasaOSMeta

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

logger = logging.getLogger(__name__)


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
    
    # 解析 JSON 响应
    from .llm_stage1 import _parse_json_response
    data = _parse_json_response(content)
    meta = CasaOSMeta.model_validate(data)
    
    logger.info("User inputs refined successfully")
    return meta
