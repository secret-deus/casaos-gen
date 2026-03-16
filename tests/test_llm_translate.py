"""Tests for casaos_gen.llm_translate module."""

import json
import unittest
from types import SimpleNamespace
from typing import Dict

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

    def create(self, model, messages, temperature):
        self.call_count += 1
        prompt = messages[0]["content"]
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
