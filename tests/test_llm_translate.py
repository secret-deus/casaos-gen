"""Tests for casaos_gen.llm_translate module."""

import json
import unittest
from types import SimpleNamespace
from typing import Dict
from unittest.mock import patch

from casaos_gen.llm_translate import (
    LLMTranslationError,
    _chunk_texts,
    _normalize_texts,
    _parse_json_object,
    build_translation_prompt,
    translate_items_with_llm,
    translate_texts_with_llm,
)


class TestParseJsonObject(unittest.TestCase):
    def test_plain_json(self):
        result = _parse_json_object('{"key": "value"}')
        self.assertEqual(result, {"key": "value"})

    def test_markdown_fenced(self):
        result = _parse_json_object('```json\n{"a": 1}\n```')
        self.assertEqual(result, {"a": 1})

    def test_leading_text(self):
        result = _parse_json_object('Sure! Here:\n{"b": 2}')
        self.assertEqual(result, {"b": 2})

    def test_invalid_json_raises(self):
        with self.assertRaises(LLMTranslationError):
            _parse_json_object("totally not json")

    def test_non_object_raises(self):
        with self.assertRaises(LLMTranslationError):
            _parse_json_object("[1, 2, 3]")

    def test_empty_string_raises(self):
        with self.assertRaises(LLMTranslationError):
            _parse_json_object("")


class TestNormalizeTexts(unittest.TestCase):
    def test_deduplication(self):
        result = _normalize_texts(["hello", "world", "hello"])
        self.assertEqual(result, ["hello", "world"])

    def test_empty_and_none_filtered(self):
        result = _normalize_texts(["", None, "  ", "valid"])
        self.assertEqual(result, ["valid"])

    def test_preserves_order(self):
        result = _normalize_texts(["b", "a", "c"])
        self.assertEqual(result, ["b", "a", "c"])

    def test_empty_input(self):
        self.assertEqual(_normalize_texts([]), [])


class TestChunkTexts(unittest.TestCase):
    def test_single_chunk(self):
        result = _chunk_texts(["a", "b", "c"], max_items=10, max_chars=1000)
        self.assertEqual(result, [["a", "b", "c"]])

    def test_split_by_items(self):
        result = _chunk_texts(["a", "b", "c", "d"], max_items=2, max_chars=1000)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], ["a", "b"])
        self.assertEqual(result[1], ["c", "d"])

    def test_split_by_chars(self):
        result = _chunk_texts(["hello", "world"], max_items=100, max_chars=6)
        self.assertEqual(len(result), 2)

    def test_empty_input(self):
        result = _chunk_texts([], max_items=10, max_chars=100)
        self.assertEqual(result, [])


class TestBuildTranslationPrompt(unittest.TestCase):
    def test_includes_items(self):
        prompt = build_translation_prompt(
            {"0": "hello"}, ["en_US", "zh_CN"], source_language="en_US"
        )
        self.assertIn("hello", prompt)
        self.assertIn("en_US", prompt)
        self.assertIn("zh_CN", prompt)

    def test_auto_detect_mode(self):
        prompt = build_translation_prompt(
            {"0": "hello"}, ["en_US", "zh_CN"], source_language=None
        )
        self.assertIn("Detect the source language", prompt)

    def test_source_language_hint(self):
        prompt = build_translation_prompt(
            {"0": "hello"}, ["en_US", "zh_CN"], source_language="en_US"
        )
        self.assertIn("source text locale is 'en_US'", prompt)


class FakeLLMClient:
    """Fake OpenAI client that returns translations with a prefix."""

    def __init__(self, prefix="tr:"):
        self.prefix = prefix
        self.chat = SimpleNamespace(completions=self)
        self.call_count = 0
        self.requested_language_sets = []

    def create(self, model, messages, temperature, max_tokens=None):
        self.call_count += 1
        prompt = messages[0]["content"]
        lines = prompt.splitlines()
        for index, line in enumerate(lines):
            if line.strip() == "Translate each SOURCE_TEXT into these target locales:":
                self.requested_language_sets.append(json.loads(lines[index + 1].strip()))
                break
        if 'locale "' in prompt:
            start = prompt.find('locale "') + len('locale "')
            end = prompt.find('"', start)
            target_language = prompt[start:end]
            marker2 = "SOURCE_TEXT:"
            idx2 = prompt.find(marker2)
            text = prompt[idx2 + len(marker2):].strip() if idx2 != -1 else "unknown"
            content = json.dumps({target_language: f"{self.prefix}{text}"}, ensure_ascii=False)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
            )
        # Extract items from the prompt
        marker = "ITEMS (ITEM_ID -> SOURCE_TEXT):"
        idx = prompt.find(marker)
        if idx != -1:
            items_json = prompt[idx + len(marker):].strip()
            items = json.loads(items_json)
        else:
            # Single text mode
            marker2 = "SOURCE_TEXT:"
            idx2 = prompt.find(marker2)
            text = prompt[idx2 + len(marker2):].strip() if idx2 != -1 else "unknown"
            items = {"0": text}

        response_obj = {}
        for item_id, source_text in items.items():
            response_obj[item_id] = {
                "en_US": source_text,
                "zh_CN": f"{self.prefix}{source_text}",
            }
        content = json.dumps(response_obj, ensure_ascii=False)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


class TestTranslateItemsWithLLM(unittest.TestCase):
    def test_default_client_uses_timeout_and_no_retries(self):
        captured_kwargs = {}

        class FakeOpenAI:
            def __init__(self, **kwargs):
                captured_kwargs.update(kwargs)
                self.chat = SimpleNamespace(completions=self)

            def create(self, model, messages, temperature, max_tokens=None):
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"zh_CN":"nihao"}'))])

        with patch("casaos_gen.llm_translate.OpenAI", FakeOpenAI):
            result = translate_items_with_llm(
                {"0": "hello"},
                ["en_US", "zh_CN"],
                model="fake",
                api_key="sk-test",
                base_url="https://example.invalid/v1",
            )

        self.assertEqual(result["0"]["en_US"], "hello")
        self.assertEqual(result["0"]["zh_CN"], "nihao")
        self.assertEqual(captured_kwargs["api_key"], "sk-test")
        self.assertEqual(captured_kwargs["base_url"], "https://example.invalid/v1")
        self.assertEqual(captured_kwargs["timeout"], 90.0)
        self.assertEqual(captured_kwargs["max_retries"], 0)

    def test_basic_translation(self):
        client = FakeLLMClient()
        result = translate_items_with_llm(
            {"0": "hello"},
            ["en_US", "zh_CN"],
            model="fake",
            client=client,
        )
        self.assertEqual(result["0"]["en_US"], "hello")
        self.assertEqual(result["0"]["zh_CN"], "tr:hello")

    def test_source_language_preserved(self):
        client = FakeLLMClient()
        result = translate_items_with_llm(
            {"0": "hello"},
            ["en_US", "zh_CN"],
            model="fake",
            client=client,
            source_language="en_US",
        )
        # Source language must match input exactly
        self.assertEqual(result["0"]["en_US"], "hello")

    def test_empty_languages_raises(self):
        client = FakeLLMClient()
        with self.assertRaises(ValueError):
            translate_items_with_llm({"0": "x"}, [], model="fake", client=client)

    def test_missing_item_in_response_uses_fallback(self):
        """When LLM doesn't return an item, fallback to source text."""
        class EmptyClient:
            def __init__(self):
                self.chat = SimpleNamespace(completions=self)
            def create(self, **kw):
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))]
                )

        result = translate_items_with_llm(
            {"0": "hello"},
            ["en_US", "zh_CN"],
            model="fake",
            client=EmptyClient(),
        )
        # Fallback: all locales should have the source text
        self.assertEqual(result["0"]["en_US"], "hello")
        self.assertEqual(result["0"]["zh_CN"], "hello")

    def test_many_languages_issue_one_request_per_locale(self):
        client = FakeLLMClient()
        languages = [
            "de_DE",
            "el_GR",
            "en_GB",
            "en_US",
            "fr_FR",
            "hr_HR",
            "it_IT",
            "ja_JP",
            "ko_KR",
            "nb_NO",
            "pt_PT",
            "ru_RU",
            "sv_SE",
            "tr_TR",
            "zh_CN",
        ]

        result = translate_items_with_llm(
            {"0": "hello"},
            languages,
            model="fake",
            client=client,
            source_language="en_US",
        )

        self.assertEqual(client.call_count, len(languages) - 1)
        self.assertEqual(result["0"]["en_US"], "hello")
        self.assertEqual(result["0"]["zh_CN"], "tr:hello")

    def test_retries_transient_failures(self):
        class FlakyClient:
            def __init__(self):
                self.chat = SimpleNamespace(completions=self)
                self.call_count = 0

            def create(self, model, messages, temperature, max_tokens=None):
                self.call_count += 1
                if self.call_count == 1:
                    raise Exception("temporary gateway timeout")
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"zh_CN":"nihao"}'))])

        client = FlakyClient()
        result = translate_items_with_llm(
            {"0": "hello"},
            ["en_US", "zh_CN"],
            model="fake",
            client=client,
            max_attempts=2,
            retry_base_delay_seconds=0.0,
        )

        self.assertEqual(client.call_count, 2)
        self.assertEqual(result["0"]["zh_CN"], "nihao")

    def test_translation_issues_one_request_per_target_locale(self):
        calls = []

        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def read(self):
                return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        def fake_urlopen(request, timeout):
            payload = json.loads(request.data.decode("utf-8"))
            prompt = payload["input"]
            calls.append(payload)
            if 'locale "zh_CN"' in prompt:
                content = '{"zh_CN":"主 Web 界面端口"}'
            elif 'locale "fr_FR"' in prompt:
                content = "{\"fr_FR\":\"Port principal de l'interface web\"}"
            else:
                content = '{"en_US":"Main web interface port"}'
            return FakeResponse({"output": [{"type": "message", "content": content}]})

        with patch("casaos_gen.lmstudio_client.urlopen", side_effect=fake_urlopen):
            result = translate_items_with_llm(
                {"0": "Main web interface port"},
                ["en_US", "zh_CN", "fr_FR"],
                model="qwen/qwen3.5-9b",
                api_key="lm-studio",
                base_url="http://127.0.0.1:1234/v1",
                source_language="en_US",
            )

        self.assertEqual(len(calls), 2)
        self.assertEqual(result["0"]["en_US"], "Main web interface port")
        self.assertEqual(result["0"]["zh_CN"], "主 Web 界面端口")
        self.assertEqual(result["0"]["fr_FR"], "Port principal de l'interface web")
        for payload in calls:
            self.assertEqual(payload["reasoning"], "off")


class TestTranslateTextsWithLLM(unittest.TestCase):
    def test_short_texts_batched(self):
        client = FakeLLMClient()
        result = translate_texts_with_llm(
            ["hello", "world"],
            ["en_US", "zh_CN"],
            model="fake",
            client=client,
        )
        self.assertIn("hello", result)
        self.assertIn("world", result)
        self.assertEqual(result["hello"]["zh_CN"], "tr:hello")

    def test_deduplication(self):
        client = FakeLLMClient()
        result = translate_texts_with_llm(
            ["hello", "hello", "hello"],
            ["en_US", "zh_CN"],
            model="fake",
            client=client,
        )
        # Only one entry since they're deduplicated
        self.assertEqual(len(result), 1)
        self.assertIn("hello", result)

    def test_empty_texts_returns_empty(self):
        client = FakeLLMClient()
        result = translate_texts_with_llm(
            [], ["en_US", "zh_CN"], model="fake", client=client,
        )
        self.assertEqual(result, {})

    def test_long_texts_translated_individually(self):
        client = FakeLLMClient()
        long_text = "Line1\nLine2\nLine3"
        result = translate_texts_with_llm(
            [long_text],
            ["en_US", "zh_CN"],
            model="fake",
            client=client,
            short_text_max_chars=5,  # Force long-text path
        )
        self.assertIn(long_text, result)

    def test_all_batches_fail_raises(self):
        class FailClient:
            def __init__(self):
                self.chat = SimpleNamespace(completions=self)
            def create(self, **kw):
                raise Exception("network error")

        with self.assertRaises(LLMTranslationError):
            translate_texts_with_llm(
                ["hello"],
                ["en_US", "zh_CN"],
                model="fake",
                client=FailClient(),
            )


if __name__ == "__main__":
    unittest.main()
