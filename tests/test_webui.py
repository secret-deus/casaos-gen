"""Tests for the FastAPI Web UI endpoints (casaos_gen.webui)."""

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from casaos_gen.webui import app, _SESSIONS, _SESSIONS_LOCK, LLM_CFG, SessionState


def _reset_sessions():
    """Clear all sessions between tests."""
    with _SESSIONS_LOCK:
        _SESSIONS.clear()


class TestSessionIsolation(unittest.TestCase):
    """Sessions must be isolated per cookie."""

    def setUp(self):
        _reset_sessions()
        self.client = TestClient(app)

    def tearDown(self):
        _reset_sessions()

    def test_new_session_created_on_first_request(self):
        resp = self.client.get("/api/state")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("casaos_sid", resp.cookies)

    def test_sessions_are_isolated(self):
        c1 = TestClient(app, cookies={})
        c2 = TestClient(app, cookies={})
        # Client 1 loads state
        r1 = c1.get("/api/state")
        self.assertEqual(r1.status_code, 200)
        sid1 = r1.cookies.get("casaos_sid")
        # Client 2 loads state
        r2 = c2.get("/api/state")
        sid2 = r2.cookies.get("casaos_sid")
        self.assertNotEqual(sid1, sid2)


class TestGetState(unittest.TestCase):
    def setUp(self):
        _reset_sessions()
        self.client = TestClient(app)

    def tearDown(self):
        _reset_sessions()

    def test_initial_state_has_no_compose(self):
        resp = self.client.get("/api/state")
        data = resp.json()
        self.assertFalse(data["has_compose"])
        self.assertFalse(data["has_meta"])
        self.assertIsNone(data["meta"])

    def test_api_key_is_masked(self):
        """API key must never be returned as a string."""
        original_key = LLM_CFG.api_key
        LLM_CFG.api_key = "sk-secret-key-1234567890"
        try:
            resp = self.client.get("/api/state")
            data = resp.json()
            llm = data["llm"]
            # api_key should be a boolean, never the raw key
            self.assertIs(llm["api_key"], True)
            self.assertIs(llm["stage1"]["api_key"], True)
            self.assertIs(llm["stage2"]["api_key"], True)
            self.assertNotIn("sk-secret", json.dumps(data))
        finally:
            LLM_CFG.api_key = original_key


class TestLoadCompose(unittest.TestCase):
    def setUp(self):
        _reset_sessions()
        self.client = TestClient(app)
        self.valid_compose = "services:\n  web:\n    image: nginx:latest\n    ports:\n      - '8080:80'\n"

    def tearDown(self):
        _reset_sessions()

    def test_load_compose_via_file(self):
        resp = self.client.post(
            "/api/compose",
            files={"file": ("docker-compose.yml", self.valid_compose, "text/yaml")},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("meta", data)
        self.assertEqual(data["meta"]["app"]["main"], "web")

    def test_load_compose_via_text(self):
        resp = self.client.post(
            "/api/compose-text",
            json={"text": self.valid_compose},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["meta"]["app"]["main"], "web")

    def test_load_compose_text_empty_fails(self):
        resp = self.client.post("/api/compose-text", json={"text": ""})
        self.assertEqual(resp.status_code, 400)

    def test_load_compose_invalid_yaml_fails(self):
        resp = self.client.post(
            "/api/compose",
            files={"file": ("bad.yml", ":::invalid:::", "text/yaml")},
        )
        self.assertEqual(resp.status_code, 400)

    def test_state_reflects_loaded_compose(self):
        self.client.post(
            "/api/compose-text",
            json={"text": self.valid_compose},
        )
        resp = self.client.get("/api/state")
        data = resp.json()
        self.assertTrue(data["has_compose"])
        self.assertTrue(data["has_meta"])
        self.assertIsNotNone(data["meta"])


class TestMetaFill(unittest.TestCase):
    def setUp(self):
        _reset_sessions()
        self.client = TestClient(app)
        compose = "services:\n  web:\n    image: nginx:latest\n    ports:\n      - '8080:80'\n"
        self.client.post("/api/compose-text", json={"text": compose})

    def tearDown(self):
        _reset_sessions()

    def test_fill_with_no_llm_no_params(self):
        resp = self.client.post(
            "/api/meta/fill",
            data={"use_llm": "false", "use_params": "false"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("No fill requested", data["message"])

    def test_fill_with_params_json(self):
        params = json.dumps({
            "app": {
                "title": "MyNginx",
                "tagline": "Fast proxy",
                "category": "Web Server",
            }
        })
        resp = self.client.post(
            "/api/meta/fill",
            data={"use_llm": "false", "use_params": "true", "params_json": params},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["meta"]["app"]["title"], "MyNginx")
        self.assertEqual(data["meta"]["app"]["tagline"], "Fast proxy")

    def test_fill_with_invalid_params_json(self):
        resp = self.client.post(
            "/api/meta/fill",
            data={"use_params": "true", "params_json": "not json"},
        )
        self.assertEqual(resp.status_code, 400)


class TestMetaUpdate(unittest.TestCase):
    def setUp(self):
        _reset_sessions()
        self.client = TestClient(app)
        compose = "services:\n  web:\n    image: nginx\n    ports:\n      - '8080:80'\n"
        self.client.post("/api/compose-text", json={"text": compose})

    def tearDown(self):
        _reset_sessions()

    def test_update_app_title(self):
        resp = self.client.post(
            "/api/meta/update",
            json={"target": "app.title", "value": "New Title"},
        )
        self.assertEqual(resp.status_code, 200)
        meta = resp.json()["meta"]
        self.assertEqual(meta["app"]["title"], "New Title")

    def test_update_unknown_app_field_fails(self):
        resp = self.client.post(
            "/api/meta/update",
            json={"target": "app.nonexistent_field", "value": "x"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_update_service_port_description(self):
        resp = self.client.post(
            "/api/meta/update",
            json={"target": "service:web:port:80", "value": "HTTP port"},
        )
        self.assertEqual(resp.status_code, 200)
        meta = resp.json()["meta"]
        port = meta["services"]["web"]["ports"][0]
        self.assertEqual(port["description"], "HTTP port")

    def test_update_invalid_target_fails(self):
        resp = self.client.post(
            "/api/meta/update",
            json={"target": "bad_target", "value": "x"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_update_nonexistent_service_fails(self):
        resp = self.client.post(
            "/api/meta/update",
            json={"target": "service:nonexist:port:80", "value": "x"},
        )
        self.assertEqual(resp.status_code, 404)


class TestExport(unittest.TestCase):
    def setUp(self):
        _reset_sessions()
        self.client = TestClient(app)
        compose = "services:\n  web:\n    image: nginx\n    ports:\n      - '8080:80'\n"
        self.client.post("/api/compose-text", json={"text": compose})

    def tearDown(self):
        _reset_sessions()

    def test_export_without_compose_fails(self):
        _reset_sessions()
        client = TestClient(app)
        resp = client.post("/api/export")
        self.assertEqual(resp.status_code, 400)

    def test_render_without_meta_fails(self):
        _reset_sessions()
        client = TestClient(app)
        resp = client.post("/api/render")
        self.assertEqual(resp.status_code, 400)

    def test_render_produces_compose(self):
        def fake_render_compose(compose_data, meta, **kwargs):
            output = dict(compose_data)
            output["x-casaos"] = {"title": {"en_US": meta.app.title or "web"}}
            return output

        with patch("casaos_gen.webui.render_compose", side_effect=fake_render_compose):
            resp = self.client.post("/api/render")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("x-casaos", data["compose"])

    def test_render_uses_request_llm_overrides(self):
        captured = {}

        def fake_render_compose(compose_data, meta, **kwargs):
            captured.update(kwargs)
            output = dict(compose_data)
            output["x-casaos"] = {"title": {"en_US": meta.app.title or "web"}}
            return output

        with patch("casaos_gen.webui.render_compose", side_effect=fake_render_compose):
            resp = self.client.post(
                "/api/render",
                data={
                    "model": "override-model",
                    "temperature": "0.7",
                    "llm_base_url": "https://example.invalid/v1",
                    "llm_api_key": "sk-override",
                },
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(captured["llm_model"], "override-model")
        self.assertEqual(captured["llm_temperature"], 0.7)
        self.assertEqual(captured["llm_base_url"], "https://example.invalid/v1")
        self.assertEqual(captured["llm_api_key"], "sk-override")

    def test_render_warning_includes_failure_reason(self):
        calls = {"count": 0}

        def flaky_render_compose(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("translation gateway timeout")
            return {"x-casaos": {}, "services": {}}

        with patch("casaos_gen.webui.render_compose", side_effect=flaky_render_compose):
            resp = self.client.post("/api/render")

        self.assertEqual(resp.status_code, 200)
        warning = resp.json()["warnings"][0]
        self.assertIn("Reason: translation gateway timeout", warning)

    def test_render_uses_stage2_default_config(self):
        captured = {}
        orig_stage1 = (
            LLM_CFG.stage1.model,
            LLM_CFG.stage1.base_url,
            LLM_CFG.stage1.api_key,
            LLM_CFG.stage1.temperature,
        )

        def fake_render_compose(compose_data, meta, **kwargs):
            captured.update(kwargs)
            output = dict(compose_data)
            output["x-casaos"] = {"title": {"en_US": meta.app.title or "web"}}
            return output

        LLM_CFG.stage1.model = "stage1-model"
        LLM_CFG.stage1.base_url = "https://stage1.invalid/v1"
        LLM_CFG.stage1.api_key = "sk-stage1"
        LLM_CFG.stage1.temperature = 0.1
        try:
            with patch("casaos_gen.webui.render_compose", side_effect=fake_render_compose):
                resp = self.client.post("/api/render")
        finally:
            LLM_CFG.stage1.model, LLM_CFG.stage1.base_url, LLM_CFG.stage1.api_key, LLM_CFG.stage1.temperature = orig_stage1

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(captured["llm_model"], "qwen/qwen3.5-9b")
        self.assertEqual(captured["llm_temperature"], 0.2)
        self.assertEqual(captured["llm_base_url"], "http://127.0.0.1:1234/v1")
        self.assertEqual(captured["llm_api_key"], "lm-studio")


class TestLLMConfig(unittest.TestCase):
    def setUp(self):
        _reset_sessions()
        self.client = TestClient(app)
        self._cfg_path = Path("llm_config.json")
        self._cfg_backup = self._cfg_path.read_text(encoding="utf-8") if self._cfg_path.exists() else None
        self._orig_model = LLM_CFG.model
        self._orig_key = LLM_CFG.api_key
        self._orig_url = LLM_CFG.base_url
        self._orig_temp = LLM_CFG.temperature
        self._orig_stage2_model = LLM_CFG.stage2.model
        self._orig_stage2_key = LLM_CFG.stage2.api_key
        self._orig_stage2_url = LLM_CFG.stage2.base_url
        self._orig_stage2_temp = LLM_CFG.stage2.temperature

    def tearDown(self):
        _reset_sessions()
        LLM_CFG.model = self._orig_model
        LLM_CFG.api_key = self._orig_key
        LLM_CFG.base_url = self._orig_url
        LLM_CFG.temperature = self._orig_temp
        LLM_CFG.stage2.model = self._orig_stage2_model
        LLM_CFG.stage2.api_key = self._orig_stage2_key
        LLM_CFG.stage2.base_url = self._orig_stage2_url
        LLM_CFG.stage2.temperature = self._orig_stage2_temp
        if self._cfg_backup is None:
            self._cfg_path.unlink(missing_ok=True)
        else:
            self._cfg_path.write_text(self._cfg_backup, encoding="utf-8")

    def test_set_llm_config(self):
        resp = self.client.post(
            "/api/llm",
            data={"model": "test-model", "temperature": "0.5"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["llm"]["model"], "test-model")
        self.assertEqual(data["llm"]["temperature"], 0.5)
        # api_key must be boolean
        self.assertIsInstance(data["llm"]["api_key"], bool)

    def test_set_llm_config_masks_api_key(self):
        resp = self.client.post(
            "/api/llm",
            data={"api_key": "sk-secret-12345"},
        )
        data = resp.json()
        self.assertIs(data["llm"]["api_key"], True)
        self.assertNotIn("sk-secret", json.dumps(data))

    def test_stage2_llm_config_is_fixed(self):
        resp = self.client.post(
            "/api/llm",
            data={
                "stage": "stage2",
                "base_url": "https://example.invalid/v1",
                "api_key": "sk-ignored",
                "model": "ignored-model",
                "temperature": "0.9",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["llm"]["stage2"]["model"], "qwen/qwen3.5-9b")
        self.assertEqual(data["llm"]["stage2"]["temperature"], 0.2)
        self.assertEqual(data["llm"]["stage2"]["base_url"], "http://127.0.0.1:1234/v1")
        self.assertIs(data["llm"]["stage2"]["api_key"], True)
        self.assertEqual(LLM_CFG.stage2.model, "qwen/qwen3.5-9b")


class TestIndexPage(unittest.TestCase):
    def test_index_returns_html(self):
        client = TestClient(app)
        resp = client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.headers["content-type"])


if __name__ == "__main__":
    unittest.main()
