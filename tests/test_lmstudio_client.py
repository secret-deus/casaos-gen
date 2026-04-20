"""Tests for LM Studio native client integration."""

import json
import unittest
from unittest.mock import patch

from casaos_gen.lmstudio_client import LMStudioNativeClient, build_llm_client, is_lmstudio_base_url


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class LMStudioClientTests(unittest.TestCase):
    def test_detects_local_lmstudio_base_url(self):
        self.assertTrue(is_lmstudio_base_url("http://127.0.0.1:1234/v1"))
        self.assertTrue(is_lmstudio_base_url("http://localhost:1234"))
        self.assertFalse(is_lmstudio_base_url("https://api.openai.com/v1"))

    def test_build_llm_client_returns_native_client_for_localhost(self):
        client = build_llm_client(
            openai_cls=object,
            api_key="lm-studio",
            base_url="http://127.0.0.1:1234/v1",
            timeout=90.0,
            max_retries=0,
        )
        self.assertIsInstance(client, LMStudioNativeClient)

    def test_build_llm_client_uses_openai_for_remote_urls(self):
        captured = {}

        class FakeOpenAI:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        client = build_llm_client(
            openai_cls=FakeOpenAI,
            api_key="sk-test",
            base_url="https://example.invalid/v1",
            timeout=90.0,
            max_retries=2,
        )
        self.assertIsInstance(client, FakeOpenAI)
        self.assertEqual(captured["api_key"], "sk-test")
        self.assertEqual(captured["base_url"], "https://example.invalid/v1")
        self.assertEqual(captured["timeout"], 90.0)
        self.assertEqual(captured["max_retries"], 2)

    def test_native_client_posts_reasoning_off_and_returns_content(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["headers"] = dict(request.header_items())
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return _FakeResponse(
                {
                    "output": [{"type": "message", "content": "{\"ok\":true}"}],
                    "stats": {"reasoning_output_tokens": 0},
                }
            )

        client = LMStudioNativeClient(
            api_url="http://127.0.0.1:1234/api/v1/chat",
            api_key="lm-studio",
            timeout=90.0,
        )
        with patch("casaos_gen.lmstudio_client.urlopen", side_effect=fake_urlopen):
            response = client.chat.completions.create(
                model="qwen/qwen3.5-9b",
                messages=[{"role": "user", "content": "Reply with JSON"}],
                temperature=0.0,
            )

        self.assertEqual(captured["url"], "http://127.0.0.1:1234/api/v1/chat")
        self.assertEqual(captured["timeout"], 90.0)
        self.assertEqual(captured["payload"]["model"], "qwen/qwen3.5-9b")
        self.assertEqual(captured["payload"]["reasoning"], "off")
        self.assertEqual(captured["payload"]["store"], False)
        self.assertEqual(captured["payload"]["input"], "Reply with JSON")
        self.assertEqual(captured["payload"]["max_output_tokens"], 4096)
        self.assertEqual(response.choices[0].message.content, "{\"ok\":true}")


if __name__ == "__main__":
    unittest.main()
