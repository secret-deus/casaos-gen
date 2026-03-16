"""Integration tests for casaos_gen.main pipeline helpers."""

import json
import tempfile
import unittest
from pathlib import Path

from casaos_gen import CasaOSMeta
from casaos_gen.exceptions import ComposeParseError
from casaos_gen.main import (
    load_meta_json,
    prepare_structure,
    run_params_stage,
    run_template_stage,
    save_meta_json,
    stage_two_from_meta,
    write_final_compose,
)
from casaos_gen.parser import build_casaos_meta
from casaos_gen.yaml_out import dump_yaml


VALID_COMPOSE = """\
services:
  web:
    image: nginx:latest
    ports:
      - "8080:80"
    environment:
      - TZ=UTC
    volumes:
      - ./html:/usr/share/nginx/html
"""

MULTI_SERVICE_COMPOSE = """\
services:
  app:
    image: myapp:latest
    ports:
      - "3000:3000"
  db:
    image: postgres:15
    environment:
      - POSTGRES_DB=mydb
    volumes:
      - pgdata:/var/lib/postgresql/data
volumes:
  pgdata:
"""


class TestPrepareStructure(unittest.TestCase):
    def test_prepare_returns_compose_and_meta(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False, encoding="utf-8") as f:
            f.write(VALID_COMPOSE)
            f.flush()
            compose, meta = prepare_structure(Path(f.name))
        self.assertIn("services", compose)
        self.assertIsInstance(meta, CasaOSMeta)
        self.assertIn("web", meta.services)

    def test_prepare_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            prepare_structure(Path("/nonexistent/compose.yml"))

    def test_prepare_no_services_raises(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False, encoding="utf-8") as f:
            f.write("version: '3'\n")
            f.flush()
            with self.assertRaises(ComposeParseError):
                prepare_structure(Path(f.name))


class TestSaveLoadMetaJson(unittest.TestCase):
    def test_roundtrip(self):
        compose = {"services": {"web": {"image": "nginx", "ports": ["80:80"]}}}
        meta = build_casaos_meta(compose)
        meta.app.title = "Test App"
        meta.app.tagline = "A test"
        meta.app.description = "Description"

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            path = Path(f.name)

        save_meta_json(meta, path)
        loaded = load_meta_json(path)
        self.assertEqual(loaded.app.title, "Test App")
        self.assertEqual(loaded.app.tagline, "A test")
        self.assertIn("web", loaded.services)


class TestStageTwoFromMeta(unittest.TestCase):
    def setUp(self):
        self.compose = {"services": {"web": {"image": "nginx", "ports": ["80:80"]}}}
        self.meta = build_casaos_meta(self.compose)
        self.meta.app.title = "Nginx"
        self.meta.app.tagline = "Web server"
        self.meta.app.description = "A fast web server"

    def test_produces_x_casaos(self):
        result = stage_two_from_meta(self.compose, self.meta, languages=["en_US"])
        self.assertIn("x-casaos", result)
        x = result["x-casaos"]
        self.assertIn("title", x)
        self.assertIn("en_US", x["title"])

    def test_multilang_expansion(self):
        result = stage_two_from_meta(
            self.compose, self.meta, languages=["en_US", "zh_CN"]
        )
        title = result["x-casaos"]["title"]
        self.assertIn("en_US", title)
        self.assertIn("zh_CN", title)

    def test_service_x_casaos_created(self):
        result = stage_two_from_meta(self.compose, self.meta, languages=["en_US"])
        svc = result["services"]["web"]
        self.assertIn("x-casaos", svc)


class TestRunParamsStage(unittest.TestCase):
    def test_generates_params_skeleton(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False, encoding="utf-8") as f:
            f.write(VALID_COMPOSE)
            f.flush()
            params = run_params_stage(Path(f.name))
        self.assertIn("app", params)
        self.assertIn("services", params)
        self.assertIn("web", params["services"])


class TestRunTemplateStage(unittest.TestCase):
    def test_template_without_params(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False, encoding="utf-8") as f:
            f.write(VALID_COMPOSE)
            f.flush()
            result = run_template_stage(Path(f.name))
        self.assertIn("x-casaos", result)
        self.assertIn("services", result)

    def test_template_with_params(self):
        import yaml
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False, encoding="utf-8") as cf:
            cf.write(VALID_COMPOSE)
            cf.flush()
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False, encoding="utf-8") as pf:
            pf.write(yaml.dump({"app": {"title": "CustomNginx", "tagline": "My proxy"}, "services": {}}))
            pf.flush()
            result = run_template_stage(Path(cf.name), params_path=Path(pf.name))
        x = result["x-casaos"]
        # title should reflect the params override
        title_val = x.get("title", {})
        if isinstance(title_val, dict):
            self.assertIn("CustomNginx", title_val.get("en_US", ""))
        else:
            self.assertIn("CustomNginx", str(title_val))


class TestWriteFinalCompose(unittest.TestCase):
    def test_write_to_file(self):
        data = {"services": {"web": {"image": "nginx"}}, "x-casaos": {"title": {"en_US": "Test"}}}
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False, encoding="utf-8") as f:
            path = Path(f.name)
        write_final_compose(data, path, dry_run=False)
        content = path.read_text(encoding="utf-8")
        self.assertIn("nginx", content)
        self.assertIn("x-casaos", content)

    def test_dry_run_does_not_write(self):
        data = {"services": {"web": {"image": "nginx"}}}
        path = Path(tempfile.mktemp(suffix=".yml"))
        write_final_compose(data, path, dry_run=True)
        # dry_run should NOT create the file
        self.assertFalse(path.exists())


class TestMultiServicePipeline(unittest.TestCase):
    """End-to-end: multi-service compose -> meta -> stage2 output."""

    def test_full_pipeline(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False, encoding="utf-8") as f:
            f.write(MULTI_SERVICE_COMPOSE)
            f.flush()
            compose, meta = prepare_structure(Path(f.name))

        self.assertIn("app", meta.services)
        self.assertIn("db", meta.services)

        # Fill descriptions manually (simulating LLM output)
        meta.app.title = "MyApp"
        meta.app.tagline = "Application stack"
        meta.app.description = "A full application stack."
        meta.services["db"].envs[0].description = "Database name"

        result = stage_two_from_meta(compose, meta, languages=["en_US", "zh_CN"])
        self.assertIn("x-casaos", result)

        # Both services should have x-casaos blocks
        for svc_name in ("app", "db"):
            svc = result["services"][svc_name]
            self.assertIn("x-casaos", svc, f"Service {svc_name} missing x-casaos")

        # Save and reload meta
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as mf:
            meta_path = Path(mf.name)
        save_meta_json(meta, meta_path)
        reloaded = load_meta_json(meta_path)
        self.assertEqual(reloaded.app.title, "MyApp")
        self.assertEqual(reloaded.services["db"].envs[0].description, "Database name")


if __name__ == "__main__":
    unittest.main()
