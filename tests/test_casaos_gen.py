import unittest
import tempfile
import json
from pathlib import Path
from types import SimpleNamespace

from casaos_gen import models
from casaos_gen.compose_normalize import normalize_compose_for_appstore
from casaos_gen.constants import CDN_BASE
from casaos_gen.i18n import load_translation_map, wrap_multilang
from casaos_gen.llm_stage1 import build_stage1_prompt
from casaos_gen.pipeline import apply_params_to_meta
from casaos_gen.pipeline import render_compose
from casaos_gen.parser import build_casaos_meta
from casaos_gen.template_stage import build_params_skeleton, build_template_compose
from casaos_gen.yaml_out import build_final_compose, dump_yaml, write_compose_file


class CasaOSParserTests(unittest.TestCase):
    def setUp(self):
        self.compose = {
            "services": {
                "web": {
                    "image": "nginx:latest",
                    "ports": ["8080:80"],
                    "environment": ["TZ=UTC", "DEBUG=1"],
                    "volumes": ["./config:/etc/nginx"],
                },
                "db": {
                    "image": "postgres:15",
                    "ports": ["5432:5432"],
                    "environment": {"POSTGRES_PASSWORD": "secret"},
                    "volumes": ["db-data:/var/lib/postgresql/data"],
                },
            }
        }

    def test_build_casaos_meta_generates_structure(self):
        meta = build_casaos_meta(self.compose)
        self.assertEqual(meta.app.main, "web")
        self.assertEqual(meta.app.port_map, "8080")
        self.assertEqual(meta.app.category, "Web Server")
        self.assertEqual(meta.app.title, "web")
        self.assertTrue(meta.app.tagline)
        self.assertTrue(meta.app.description)
        self.assertIn("db", meta.services)
        self.assertEqual(meta.services["db"].ports[0].container, "5432")
        self.assertEqual(len(meta.services["web"].envs), 2)

    def test_infer_main_port_supports_env_default(self):
        compose = {
            "services": {
                "db": {"image": "mysql:8", "ports": ["3306:3306"]},
                "web": {
                    "image": "nginx:latest",
                    "ports": ["${WEB_LISTEN_ADDR:-8888}:80"],
                },
            }
        }
        meta = build_casaos_meta(compose)
        self.assertEqual(meta.app.main, "web")
        self.assertEqual(meta.app.port_map, "8888")

    def test_apply_params_substitutes_store_folder_placeholders(self):
        meta = build_casaos_meta(self.compose)
        params = {
            "app": {
                "store_folder": "NocoDB",
                "icon": f"{CDN_BASE}/<store_folder>/icon.png",
                "thumbnail": f"{CDN_BASE}/<store_folder>/thumbnail.png",
                "screenshot_link": [
                    f"{CDN_BASE}/<store_folder>/screenshot-1.png",
                ],
            }
        }
        out = apply_params_to_meta(meta, params)
        self.assertEqual(out.app.icon, f"{CDN_BASE}/NocoDB/icon.png")
        self.assertEqual(out.app.thumbnail, f"{CDN_BASE}/NocoDB/thumbnail.png")
        self.assertEqual(out.app.screenshot_link[0], f"{CDN_BASE}/NocoDB/screenshot-1.png")

    def test_apply_params_strips_text_fields(self):
        """apply_params_to_meta should strip whitespace from text fields."""
        meta = build_casaos_meta(self.compose)
        params = {
            "app": {
                "title": "  My App  ",
                "tagline": "Great tagline\n",
                "description": "Multi-line desc\n\nWith paragraphs\n",
            }
        }
        out = apply_params_to_meta(meta, params)
        self.assertEqual(out.app.title, "My App")
        self.assertEqual(out.app.tagline, "Great tagline")
        self.assertEqual(out.app.description, "Multi-line desc\n\nWith paragraphs")


class CasaOSI18NTests(unittest.TestCase):
    def test_wrap_multilang_uses_translation_table(self):
        translation_file = Path("casaos_gen/translations.yml")
        translations = load_translation_map(translation_file)
        wrapped = wrap_multilang(
            "Main web interface port",
            ["en_US", "zh_CN", "de_DE"],
            translation_map=translations,
        )
        self.assertEqual(wrapped["zh_CN"], "主 Web 界面端口")
        self.assertEqual(wrapped["de_DE"], "Haupt-Weboberflächen-Port")

        fallback = wrap_multilang("Custom text", ["en_US", "ru_RU"])
        self.assertEqual(fallback["ru_RU"], "Custom text")

    def test_wrap_multilang_strips_key_for_lookup(self):
        """wrap_multilang should find translations even when english text has trailing whitespace."""
        custom_map = {
            "Main web interface port": {"zh_CN": "主端口", "de_DE": "Hauptport"},
        }
        # Text with trailing newline — must still match the stripped key
        wrapped = wrap_multilang(
            "Main web interface port\n",
            ["en_US", "zh_CN", "de_DE"],
            translation_map=custom_map,
        )
        self.assertEqual(wrapped["en_US"], "Main web interface port\n")
        self.assertEqual(wrapped["zh_CN"], "主端口")
        self.assertEqual(wrapped["de_DE"], "Hauptport")

        # Text with trailing spaces
        wrapped2 = wrap_multilang(
            "Main web interface port   ",
            ["en_US", "zh_CN"],
            translation_map=custom_map,
        )
        self.assertEqual(wrapped2["zh_CN"], "主端口")

    def test_build_final_compose_injects_metadata(self):
        translation_file = Path("casaos_gen/translations.yml")
        translations = load_translation_map(translation_file)
        meta = models.CasaOSMeta(
            app=models.AppMeta(
                title="Sample",
                tagline="Simple",
                description="Sample app",
                category="Web Server",
                author="me",
                main="web",
                port_map="8080",
            ),
            services={
                "web": models.ServiceMeta(
                    ports=[models.PortItem(container="80", description="Main web interface port")],
                    volumes=[models.VolumeItem(container="/data", description="Data directory")],
                )
            },
        )
        original = {"services": {"web": {"image": "nginx"}}}
        final = build_final_compose(original, meta, ["en_US", "zh_CN"], translations)
        self.assertIn("x-casaos", final)
        self.assertIn("x-casaos", final["services"]["web"])
        self.assertEqual(final["services"]["web"]["restart"], "unless-stopped")
        zh_desc = final["services"]["web"]["x-casaos"]["ports"][0]["description"]["zh_CN"]
        self.assertEqual(zh_desc, "主 Web 界面端口")

    def test_build_final_compose_preserves_restart_when_set(self):
        translation_file = Path("casaos_gen/translations.yml")
        translations = load_translation_map(translation_file)
        meta = models.CasaOSMeta(
            app=models.AppMeta(
                title="Sample",
                tagline="Simple",
                description="Sample app",
                category="Web Server",
                author="me",
                main="web",
                port_map="8080",
            ),
            services={},
        )
        original = {"services": {"web": {"image": "nginx", "restart": "always"}}}
        final = build_final_compose(original, meta, ["en_US"], translations)
        self.assertEqual(final["services"]["web"]["restart"], "always")


class CasaOSLLMPromptTests(unittest.TestCase):
    def test_stage1_prompt_includes_app_description_structure(self):
        meta = models.CasaOSMeta(
            app=models.AppMeta(
                title="demo",
                tagline="",
                description="",
                category="Utilities",
                author="me",
                main="demo",
                port_map="8080",
            ),
            services={},
        )
        prompt = build_stage1_prompt(meta)
        self.assertIn("Key Features", prompt)
        self.assertIn("Learn More", prompt)

    def test_stage1_prompt_accepts_custom_instructions(self):
        meta = models.CasaOSMeta(
            app=models.AppMeta(
                title="demo",
                tagline="",
                description="",
                category="Utilities",
                author="me",
                main="demo",
                port_map="8080",
            ),
            services={},
        )
        prompt = build_stage1_prompt(meta, custom_prompt="CUSTOM_RULE: hello")
        self.assertIn("CUSTOM_RULE: hello", prompt)


class CasaOSStage2LLMTranslationTests(unittest.TestCase):
    def test_render_compose_auto_translate_fills_locales_via_llm(self):
        class FakeLLMClient:
            def __init__(self) -> None:
                self.chat = SimpleNamespace(completions=self)

            def create(self, model, messages, temperature):
                prompt = messages[0]["content"]
                marker = "ITEMS (ITEM_ID -> SOURCE_TEXT):"
                index = prompt.find(marker)
                if index == -1:
                    raise AssertionError("LLM prompt missing ITEMS marker")
                items_json = prompt[index + len(marker) :].strip()
                items = json.loads(items_json)

                response_obj = {}
                for item_id, source_text in items.items():
                    response_obj[item_id] = {
                        "en_US": source_text,
                        "zh_CN": f"中文:{source_text}",
                    }

                content = json.dumps(response_obj, ensure_ascii=False)
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

        compose = {
            "services": {"web": {"image": "nginx"}},
            "x-casaos": {"tips": {"before_install": "Run setup"}},
        }
        meta = models.CasaOSMeta(
            app=models.AppMeta(
                title="Sample",
                tagline="Deep document RAG",
                description="Line1\n\nLine2",
                category="Web Server",
                author="me",
                main="web",
                port_map="8080",
            ),
            services={
                "web": models.ServiceMeta(
                    ports=[models.PortItem(container="80", description="Main web interface port")],
                    envs=[models.EnvItem(container="TZ", description="Time Zone")],
                    volumes=[models.VolumeItem(container="/data", description="Data directory")],
                )
            },
        )

        # Simulate an earlier run where locales were populated by copying en_US.
        translation_cache = {"Deep document RAG": {"zh_CN": "Deep document RAG"}}

        out = render_compose(
            compose,
            meta,
            languages=["en_US", "zh_CN"],
            translation_map_override=translation_cache,
            auto_translate=True,
            llm_model="fake-model",
            llm_temperature=0.2,
            llm_client=FakeLLMClient(),
        )

        self.assertEqual(out["x-casaos"]["tagline"]["zh_CN"], "中文:Deep document RAG")
        self.assertEqual(out["x-casaos"]["tips"]["before_install"]["zh_CN"], "中文:Run setup")
        self.assertEqual(
            out["services"]["web"]["x-casaos"]["ports"][0]["description"]["zh_CN"],
            "中文:Main web interface port",
        )
        self.assertEqual(translation_cache["Deep document RAG"]["zh_CN"], "中文:Deep document RAG")


class CasaOSTemplateStageTests(unittest.TestCase):
    def test_template_stage_builds_required_fields_and_i18n(self):
        compose = {
            "name": "ragflow",
            "services": {
                "web": {
                    "image": "nginx:latest",
                    "ports": ["8080:80"],
                    "environment": ["TZ=UTC"],
                    "volumes": ["./data:/data"],
                }
            },
        }
        params = {
            "app": {
                "store_folder": "RagFlow",
                "author": "IceWhaleTech",
                "title": "RagFlow",
                "tagline": "Deep document RAG",
            }
        }
        out = build_template_compose(compose, params=params, languages=["en_US", "zh_CN"])
        app = out["x-casaos"]
        self.assertEqual(
            app["icon"],
            "https://cdn.jsdelivr.net/gh/IceWhaleTech/CasaOS-AppStore@main/Apps/RagFlow/icon.png",
        )
        self.assertEqual(len(app["screenshot_link"]), 3)
        self.assertEqual(app["architectures"], ["amd64", "arm64"])
        self.assertEqual(app["developer"], "fromxiaobai")
        self.assertIsInstance(app["title"], dict)
        self.assertEqual(app["tagline"]["zh_CN"], "Deep document RAG")

        svc_x = out["services"]["web"]["x-casaos"]
        self.assertEqual(svc_x["ports"][0]["container"], "80")
        self.assertIn("zh_CN", svc_x["ports"][0]["description"])
        self.assertEqual(out["services"]["web"]["restart"], "unless-stopped")

    def test_params_skeleton_is_generated_by_program(self):
        compose = {
            "name": "demo",
            "services": {"web": {"image": "owner/app:latest", "ports": ["8080:80"]}},
        }
        params = build_params_skeleton(compose)
        self.assertIn("app", params)
        self.assertIn("services", params)
        self.assertEqual(params["app"]["developer"], "fromxiaobai")
        self.assertEqual(params["app"]["architectures"], ["amd64", "arm64"])
        self.assertEqual(params["app"]["author"], "owner")
        self.assertEqual(params["services"]["web"]["ports"][0]["container"], "80")

    def test_yaml_write_allows_unicode(self):
        data = {"x": "这里是中文", "y": "⏳"}
        tmp_file = tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False, encoding="utf-8")
        try:
            path = Path(tmp_file.name)
        finally:
            tmp_file.close()

        try:
            write_compose_file(data, path)
            text = path.read_text(encoding="utf-8")
            self.assertIn("这里是中文", text)
            self.assertIn("⏳", text)
        finally:
            path.unlink(missing_ok=True)

    def test_dump_yaml_indents_list_items(self):
        text = dump_yaml({"a": ["x", "y"], "b": {"c": [1, 2]}})
        self.assertIn("a:\n  -", text)
        self.assertIn("b:\n  c:\n    -", text)

    def test_dump_yaml_uses_block_scalars_for_multiline_strings(self):
        text = dump_yaml({"x-casaos": {"description": {"zh_CN": "line1\n\nline2\n- item"}}})
        self.assertIn("zh_CN: |", text)
        self.assertNotIn("\\n", text)

    def test_dump_yaml_uses_double_quotes_for_special_fields(self):
        compose = {
            "services": {
                "app": {
                    "ports": [
                        {"target": 80, "published": "12345", "protocol": "tcp"},
                    ],
                    "x-casaos": {
                        "ports": [
                            {"container": "80", "description": {"en_US": "API Port"}},
                        ]
                    },
                }
            },
            "x-casaos": {"port_map": "12345"},
        }
        text = dump_yaml(compose)
        self.assertIn('published: "12345"', text)
        self.assertIn('port_map: "12345"', text)
        self.assertIn('container: "80"', text)


class CasaOSComposeNormalizeTests(unittest.TestCase):
    def test_normalize_fills_cdn_media_links_when_missing(self):
        compose = {
            "services": {"web": {"image": "nginx"}},
            "x-casaos": {
                "title": {"en_US": "nocodb"},
                "icon": "",
                "thumbnail": "",
                "screenshot_link": [],
            },
        }
        out = normalize_compose_for_appstore(compose, store_folder="NocoDB")
        self.assertEqual(out["x-casaos"]["icon"], f"{CDN_BASE}/NocoDB/icon.png")
        self.assertEqual(out["x-casaos"]["thumbnail"], f"{CDN_BASE}/NocoDB/thumbnail.png")
        self.assertEqual(
            out["x-casaos"]["screenshot_link"][0], f"{CDN_BASE}/NocoDB/screenshot-1.png"
        )

    def test_normalize_replaces_store_folder_placeholders_in_media_links(self):
        compose = {
            "services": {"web": {"image": "nginx"}},
            "x-casaos": {
                "title": {"en_US": "nocodb"},
                "icon": f"{CDN_BASE}/<store_folder>/icon.png",
                "thumbnail": f"{CDN_BASE}/<store_folder>/thumbnail.png",
                "screenshot_link": [
                    f"{CDN_BASE}/<store_folder>/screenshot-1.png",
                    f"{CDN_BASE}/<store_folder>/screenshot-2.png",
                ],
            },
        }
        out = normalize_compose_for_appstore(compose, store_folder="NocoDB")
        self.assertEqual(out["x-casaos"]["icon"], f"{CDN_BASE}/NocoDB/icon.png")
        self.assertEqual(out["x-casaos"]["thumbnail"], f"{CDN_BASE}/NocoDB/thumbnail.png")
        self.assertEqual(out["x-casaos"]["screenshot_link"][0], f"{CDN_BASE}/NocoDB/screenshot-1.png")

    def test_normalize_uses_explicit_port_map_when_overriding_published(self):
        compose = {
            "services": {
                "app": {"image": "nginx:latest", "ports": ["80:80"]},
            },
            "x-casaos": {"main": "app", "port_map": "28410"},
        }
        out = normalize_compose_for_appstore(compose, store_folder="demo")
        ports = out["services"]["app"]["ports"]
        self.assertEqual(ports[0]["published"], "28410")
        self.assertEqual(out["x-casaos"]["port_map"], "28410")

    def test_normalize_converts_ports_and_volumes_to_long_syntax(self):
        compose = {
            "version": "3.8",
            "services": {
                "nocodb": {
                    "image": "nocodb/nocodb:latest",
                    "ports": ["8080:8080"],
                    "volumes": ["nocodb_data:/usr/app/data"],
                }
            },
            "volumes": {"nocodb_data": None},
        }
        out = normalize_compose_for_appstore(compose, store_folder="nocodb")
        self.assertEqual(out["services"]["nocodb"]["restart"], "unless-stopped")
        ports = out["services"]["nocodb"]["ports"]
        self.assertIsInstance(ports, list)
        self.assertIsInstance(ports[0], dict)
        self.assertEqual(ports[0]["target"], 8080)
        self.assertEqual(ports[0]["published"], "8080")
        self.assertEqual(ports[0]["protocol"], "tcp")

        volumes = out["services"]["nocodb"]["volumes"]
        self.assertIsInstance(volumes, list)
        self.assertEqual(volumes[0]["type"], "bind")
        self.assertEqual(volumes[0]["source"], "/DATA/AppData/$AppID/data")
        self.assertEqual(volumes[0]["target"], "/usr/app/data")
        self.assertNotIn("bind", volumes[0])

        self.assertNotIn("volumes", out)

    def test_normalize_aligns_port_map_with_published_when_x_casaos_present(self):
        compose = {
            "services": {
                "app": {"image": "nginx:latest", "ports": ["8080:8080"]},
            },
            "x-casaos": {"main": "app", "port_map": "8080"},
        }
        out = normalize_compose_for_appstore(compose, store_folder="demo")
        ports = out["services"]["app"]["ports"]
        self.assertEqual(out["x-casaos"]["port_map"], ports[0]["published"])
        self.assertTrue(ports[0]["published"].isdigit())
        self.assertLess(int(ports[0]["published"]), 30000)

    def test_normalize_keeps_explicit_bind_sources(self):
        compose = {
            "services": {
                "app": {
                    "image": "example",
                    "volumes": ["/DATA/Media/Music:/music"],
                }
            }
        }
        out = normalize_compose_for_appstore(compose, store_folder="demo")
        volumes = out["services"]["app"]["volumes"]
        self.assertEqual(volumes[0]["type"], "bind")
        self.assertEqual(volumes[0]["source"], "/DATA/Media/Music")
        self.assertEqual(volumes[0]["target"], "/music")

    def test_normalize_converts_relative_bind_sources_to_appdata(self):
        compose = {
            "services": {
                "db": {
                    "image": "postgres:16",
                    "volumes": ["./data/postgres:/var/lib/postgresql/data"],
                }
            }
        }
        out = normalize_compose_for_appstore(compose, store_folder="demo")
        volumes = out["services"]["db"]["volumes"]
        self.assertEqual(volumes[0]["type"], "bind")
        self.assertEqual(volumes[0]["source"], "/DATA/AppData/$AppID/data/postgres")
        self.assertEqual(volumes[0]["target"], "/var/lib/postgresql/data")

    def test_normalize_converts_yaml_mapping_ports(self):
        compose = {
            "services": {
                "app": {
                    "image": "example",
                    # YAML like: - 880:8080 can be parsed as a 1-item dict.
                    "ports": [{880: 8080}],
                }
            }
        }
        out = normalize_compose_for_appstore(compose, store_folder="demo")
        ports = out["services"]["app"]["ports"]
        self.assertEqual(ports[0]["target"], 8080)
        self.assertEqual(ports[0]["published"], "880")
        self.assertEqual(ports[0]["protocol"], "tcp")


# ========== Phase 3: Core module tests ==========

import logging
import os
import shutil
import time as _time

from casaos_gen.infer import (
    normalize_port_value,
    parse_port_entry,
    collect_port_pairs,
    infer_main_service,
    infer_main_port,
    infer_category,
    infer_author,
)
from casaos_gen.diff_engine import (
    compute_compose_diff,
    merge_meta_with_diff,
    ComposeDiff,
)
from casaos_gen.version_manager import VersionManager
from casaos_gen.incremental import (
    incremental_update,
    show_compose_diff as show_diff,
    get_version_history,
)
from casaos_gen.cli import build_parser, configure_logging


class TestNormalizePortValue(unittest.TestCase):
    def test_plain_number(self):
        self.assertEqual(normalize_port_value("8080"), "8080")

    def test_none(self):
        self.assertIsNone(normalize_port_value(None))

    def test_empty_string(self):
        self.assertIsNone(normalize_port_value(""))

    def test_whitespace(self):
        self.assertIsNone(normalize_port_value("  "))

    def test_env_default_colon_dash(self):
        self.assertEqual(normalize_port_value("${WEB_PORT:-8888}"), "8888")

    def test_env_default_dash(self):
        self.assertEqual(normalize_port_value("${WEB_PORT-8888}"), "8888")

    def test_env_no_default(self):
        self.assertIsNone(normalize_port_value("${WEB_PORT}"))

    def test_non_numeric(self):
        self.assertIsNone(normalize_port_value("abc"))


class TestParsePortEntry(unittest.TestCase):
    def test_integer(self):
        host, container = parse_port_entry(80)
        self.assertEqual(host, "80")
        self.assertEqual(container, "80")

    def test_string_mapping(self):
        host, container = parse_port_entry("8080:80")
        self.assertEqual(host, "8080")
        self.assertEqual(container, "80")

    def test_protocol_stripped(self):
        host, container = parse_port_entry("8080:80/tcp")
        self.assertEqual(host, "8080")
        self.assertEqual(container, "80")

    def test_container_only(self):
        host, container = parse_port_entry("80")
        self.assertIsNone(host)
        self.assertEqual(container, "80")

    def test_dict_entry(self):
        host, container = parse_port_entry({"published": "8080", "target": "80"})
        self.assertEqual(host, "8080")
        self.assertEqual(container, "80")

    def test_ip_prefix(self):
        host, container = parse_port_entry("127.0.0.1:8080:80")
        self.assertEqual(host, "8080")
        self.assertEqual(container, "80")

    def test_unsupported_type(self):
        host, container = parse_port_entry([1, 2, 3])
        self.assertIsNone(host)
        self.assertIsNone(container)

    def test_env_var_in_mapping(self):
        host, container = parse_port_entry("${WEB_PORT:-8888}:80")
        self.assertEqual(host, "${WEB_PORT:-8888}")
        self.assertEqual(container, "80")


class TestCollectPortPairs(unittest.TestCase):
    def test_empty_service(self):
        self.assertEqual(collect_port_pairs({}), [])

    def test_basic_extraction(self):
        svc = {"ports": ["8080:80", "443:443"]}
        pairs = collect_port_pairs(svc)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(pairs[0], ("8080", "80"))
        self.assertEqual(pairs[1], ("443", "443"))


class TestInferMainService(unittest.TestCase):
    def test_single_service(self):
        self.assertEqual(infer_main_service({"web": {"image": "nginx"}}), "web")

    def test_http_port_priority(self):
        services = {
            "db": {"image": "postgres", "ports": ["5432:5432"]},
            "web": {"image": "nginx", "ports": ["8080:80"]},
        }
        self.assertEqual(infer_main_service(services), "web")

    def test_preferred_name_fallback(self):
        services = {
            "db": {"image": "postgres", "ports": ["5432:5432"]},
            "app": {"image": "myapp", "ports": ["9090:9090"]},
        }
        self.assertEqual(infer_main_service(services), "app")

    def test_first_entry_fallback(self):
        services = {
            "redis": {"image": "redis"},
            "worker": {"image": "worker"},
        }
        result = infer_main_service(services)
        self.assertEqual(result, "redis")

    def test_empty_services_raises(self):
        with self.assertRaises(ValueError):
            infer_main_service({})


class TestInferMainPort(unittest.TestCase):
    def test_http_friendly_port(self):
        svc = {"ports": ["8080:80"]}
        self.assertEqual(infer_main_port(svc), "8080")

    def test_non_http_port(self):
        svc = {"ports": ["9090:9090"]}
        self.assertEqual(infer_main_port(svc), "9090")

    def test_no_ports(self):
        self.assertEqual(infer_main_port({}), "")


class TestInferCategory(unittest.TestCase):
    def test_preferred_service_match(self):
        services = {
            "web": {"image": "nginx:latest"},
            "db": {"image": "postgres:15"},
        }
        self.assertEqual(infer_category(services, preferred_service="web"), "Web Server")

    def test_any_service_match(self):
        services = {"db": {"image": "postgres:15"}}
        self.assertEqual(infer_category(services), "Database")

    def test_unknown_defaults_utilities(self):
        services = {"foo": {"image": "custom-app:latest"}}
        self.assertEqual(infer_category(services), "Utilities")


class TestInferAuthor(unittest.TestCase):
    def test_with_namespace(self):
        services = {"web": {"image": "myorg/myapp:latest"}}
        self.assertEqual(infer_author(services, preferred_service="web"), "myorg")

    def test_without_namespace(self):
        services = {"web": {"image": "nginx:latest"}}
        self.assertEqual(infer_author(services), "CasaOS User")

    def test_preferred_service_priority(self):
        services = {
            "db": {"image": "postgres/pg:15"},
            "web": {"image": "myorg/app:latest"},
        }
        self.assertEqual(infer_author(services, preferred_service="web"), "myorg")


class TestComputeComposeDiff(unittest.TestCase):
    def test_no_changes(self):
        compose = {"services": {"web": {"image": "nginx", "ports": ["80:80"]}}}
        diff = compute_compose_diff(compose, compose)
        self.assertFalse(diff.has_changes())
        self.assertIn("无变更", diff.summary())

    def test_added_service(self):
        old = {"services": {"web": {"image": "nginx"}}}
        new = {"services": {"web": {"image": "nginx"}, "db": {"image": "postgres", "ports": ["5432:5432"]}}}
        diff = compute_compose_diff(old, new)
        self.assertIn("db", diff.added_services)
        self.assertTrue(diff.has_changes())

    def test_removed_service(self):
        old = {"services": {"web": {"image": "nginx"}, "db": {"image": "postgres"}}}
        new = {"services": {"web": {"image": "nginx"}}}
        diff = compute_compose_diff(old, new)
        self.assertIn("db", diff.removed_services)

    def test_added_port(self):
        old = {"services": {"web": {"image": "nginx", "ports": ["80:80"]}}}
        new = {"services": {"web": {"image": "nginx", "ports": ["80:80", "443:443"]}}}
        diff = compute_compose_diff(old, new)
        added_paths = [f.path for f in diff.added_fields]
        self.assertTrue(any("443" in p for p in added_paths))

    def test_removed_env(self):
        old = {"services": {"web": {"image": "nginx", "environment": ["TZ=UTC", "DEBUG=1"]}}}
        new = {"services": {"web": {"image": "nginx", "environment": ["TZ=UTC"]}}}
        diff = compute_compose_diff(old, new)
        removed_paths = [f.path for f in diff.removed_fields]
        self.assertTrue(any("DEBUG" in p for p in removed_paths))

    def test_summary_truncation(self):
        old = {"services": {"web": {"image": "nginx"}}}
        new = {"services": {"web": {"image": "nginx"}, "a": {"image": "a", "ports": [f"{i}:{i}" for i in range(10)]}}}
        diff = compute_compose_diff(old, new)
        summary = diff.summary()
        self.assertIn("还有", summary)


class TestMergeMetaWithDiff(unittest.TestCase):
    def test_preserves_old_description(self):
        old_meta = models.CasaOSMeta(
            app=models.AppMeta(
                title="MyApp", tagline="Old tagline", description="A" * 150,
                category="Web Server", author="me", main="web", port_map="80",
            ),
            services={
                "web": models.ServiceMeta(
                    ports=[models.PortItem(container="80", description="Old port desc")],
                )
            },
        )
        new_meta = models.CasaOSMeta(
            app=models.AppMeta(
                title="web", tagline="web on CasaOS", description="",
                category="Web Server", author="me", main="web", port_map="80",
            ),
            services={
                "web": models.ServiceMeta(
                    ports=[models.PortItem(container="80", description="")],
                )
            },
        )
        diff = ComposeDiff()
        merged = merge_meta_with_diff(old_meta, new_meta, diff)
        self.assertEqual(merged.app.title, "MyApp")
        self.assertEqual(merged.app.description, "A" * 150)
        self.assertEqual(merged.services["web"].ports[0].description, "Old port desc")

    def test_new_fields_are_empty(self):
        old_meta = models.CasaOSMeta(
            app=models.AppMeta(
                title="App", tagline="Tag", description="Desc",
                category="Utilities", author="me", main="web", port_map="80",
            ),
            services={},
        )
        new_meta = models.CasaOSMeta(
            app=models.AppMeta(
                title="App", tagline="Tag", description="Desc",
                category="Utilities", author="me", main="web", port_map="80",
            ),
            services={
                "db": models.ServiceMeta(
                    ports=[models.PortItem(container="5432", description="")],
                )
            },
        )
        diff = ComposeDiff(added_services={"db"})
        merged = merge_meta_with_diff(old_meta, new_meta, diff)
        self.assertEqual(merged.services["db"].ports[0].description, "")


class TestVersionManager(unittest.TestCase):
    def setUp(self):
        self.work_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.work_dir)

    def test_init_creates_dirs(self):
        vm = VersionManager(self.work_dir)
        self.assertTrue(Path(self.work_dir).exists())
        self.assertTrue(vm.history_dir.exists())

    def test_compute_hash(self):
        vm = VersionManager(self.work_dir)
        tmp = Path(self.work_dir) / "test.yml"
        tmp.write_text("hello", encoding="utf-8")
        h = vm.compute_compose_hash(tmp)
        self.assertEqual(len(h), 64)  # SHA256 hex

    def test_compute_hash_missing_file(self):
        vm = VersionManager(self.work_dir)
        h = vm.compute_compose_hash(Path(self.work_dir) / "nonexistent.yml")
        self.assertEqual(h, "")

    def test_has_compose_changed_first_time(self):
        vm = VersionManager(self.work_dir)
        tmp = Path(self.work_dir) / "test.yml"
        tmp.write_text("hello", encoding="utf-8")
        self.assertTrue(vm.has_compose_changed(tmp))

    def test_has_compose_changed_no_change(self):
        vm = VersionManager(self.work_dir)
        tmp = Path(self.work_dir) / "test.yml"
        tmp.write_text("hello", encoding="utf-8")
        vm.update_compose_hash(tmp)
        self.assertFalse(vm.has_compose_changed(tmp))

    def test_has_compose_changed_with_change(self):
        vm = VersionManager(self.work_dir)
        tmp = Path(self.work_dir) / "test.yml"
        tmp.write_text("hello", encoding="utf-8")
        vm.update_compose_hash(tmp)
        tmp.write_text("world", encoding="utf-8")
        self.assertTrue(vm.has_compose_changed(tmp))

    def test_save_and_load_meta(self):
        vm = VersionManager(self.work_dir)
        meta = models.CasaOSMeta(
            app=models.AppMeta(
                title="Test", tagline="Tag", description="Desc",
                category="Utilities", author="me", main="web", port_map="80",
            ),
            services={},
        )
        vm.save_current_meta(meta)
        loaded = vm.load_current_meta()
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.app.title, "Test")

    def test_load_meta_missing(self):
        vm = VersionManager(self.work_dir)
        self.assertIsNone(vm.load_current_meta())

    def test_backup_to_history(self):
        vm = VersionManager(self.work_dir)
        meta = models.CasaOSMeta(
            app=models.AppMeta(
                title="Test", tagline="Tag", description="Desc",
                category="Utilities", author="me", main="web", port_map="80",
            ),
            services={},
        )
        vm.save_current_meta(meta)
        backup_path = vm.backup_to_history()
        self.assertIsNotNone(backup_path)
        self.assertTrue(backup_path.exists())

    def test_backup_without_current_returns_none(self):
        vm = VersionManager(self.work_dir)
        self.assertIsNone(vm.backup_to_history())

    def test_list_history(self):
        vm = VersionManager(self.work_dir)
        meta = models.CasaOSMeta(
            app=models.AppMeta(
                title="Test", tagline="Tag", description="Desc",
                category="Utilities", author="me", main="web", port_map="80",
            ),
            services={},
        )
        vm.save_current_meta(meta)
        vm.backup_to_history()
        versions = vm.list_history()
        self.assertGreaterEqual(len(versions), 1)

    def test_rollback(self):
        vm = VersionManager(self.work_dir)
        meta1 = models.CasaOSMeta(
            app=models.AppMeta(
                title="V1", tagline="Tag", description="Desc",
                category="Utilities", author="me", main="web", port_map="80",
            ),
            services={},
        )
        vm.save_current_meta(meta1)
        backup = vm.backup_to_history()

        # Ensure different timestamp for next backup
        _time.sleep(1.1)

        meta2 = models.CasaOSMeta(
            app=models.AppMeta(
                title="V2", tagline="Tag", description="Desc",
                category="Utilities", author="me", main="web", port_map="80",
            ),
            services={},
        )
        vm.save_current_meta(meta2)

        vm.rollback_to_version(backup.name)
        loaded = vm.load_current_meta()
        self.assertEqual(loaded.app.title, "V1")

    def test_rollback_nonexistent_raises(self):
        vm = VersionManager(self.work_dir)
        with self.assertRaises(FileNotFoundError):
            vm.rollback_to_version("nonexistent.json")

    def test_compose_backup(self):
        vm = VersionManager(self.work_dir)
        tmp = Path(self.work_dir) / "compose.yml"
        tmp.write_text("services:\n  web:\n    image: nginx", encoding="utf-8")
        vm.backup_compose_file(tmp)
        backed = vm.get_backed_up_compose()
        self.assertIsNotNone(backed)
        self.assertTrue(backed.exists())

    def test_get_backed_up_compose_missing(self):
        vm = VersionManager(self.work_dir)
        self.assertIsNone(vm.get_backed_up_compose())

    def test_config_management(self):
        vm = VersionManager(self.work_dir)
        config = {"max_history_versions": 5, "enable_version_control": True}
        vm.save_config(config)
        loaded = vm._load_config()
        self.assertEqual(loaded["max_history_versions"], 5)

    def test_cleanup_old_versions(self):
        vm = VersionManager(self.work_dir)
        vm.save_config({"max_history_versions": 2})
        meta = models.CasaOSMeta(
            app=models.AppMeta(
                title="Test", tagline="Tag", description="Desc",
                category="Utilities", author="me", main="web", port_map="80",
            ),
            services={},
        )
        # Create 4 backups
        for i in range(4):
            vm.save_current_meta(meta)
            vm.backup_to_history()
            import time as _time
            _time.sleep(0.05)  # Ensure different timestamps

        versions = vm.list_history()
        self.assertLessEqual(len(versions), 2)


class TestIncremental(unittest.TestCase):
    def setUp(self):
        self.work_dir = tempfile.mkdtemp()
        self.compose_path = Path(self.work_dir) / "docker-compose.yml"

    def tearDown(self):
        shutil.rmtree(self.work_dir)

    def _write_compose(self, services_dict):
        import yaml as _yaml
        data = {"services": services_dict}
        self.compose_path.write_text(_yaml.dump(data), encoding="utf-8")

    def test_first_run_generates_full_meta(self):
        self._write_compose({"web": {"image": "nginx:latest", "ports": ["8080:80"]}})
        meta, diff = incremental_update(
            self.compose_path, work_dir=self.work_dir
        )
        self.assertIsNotNone(meta)
        self.assertIsNone(diff)
        self.assertEqual(meta.app.main, "web")

    def test_no_change_uses_cache(self):
        self._write_compose({"web": {"image": "nginx:latest", "ports": ["8080:80"]}})
        meta1, _ = incremental_update(self.compose_path, work_dir=self.work_dir)
        meta2, diff2 = incremental_update(self.compose_path, work_dir=self.work_dir)
        self.assertIsNone(diff2)
        self.assertEqual(meta2.app.title, meta1.app.title)

    def test_force_regenerate_ignores_cache(self):
        self._write_compose({"web": {"image": "nginx:latest", "ports": ["8080:80"]}})
        incremental_update(self.compose_path, work_dir=self.work_dir)
        meta, diff = incremental_update(
            self.compose_path, work_dir=self.work_dir, force_regenerate=True
        )
        self.assertIsNotNone(meta)
        self.assertIsNone(diff)  # Force regenerate does full build, no diff

    def test_empty_version_history(self):
        versions = get_version_history(self.work_dir)
        self.assertEqual(versions, [])

    def test_show_diff_no_backup_returns_none(self):
        self._write_compose({"web": {"image": "nginx:latest"}})
        result = show_diff(self.compose_path, self.work_dir)
        self.assertIsNone(result)


class TestCLI(unittest.TestCase):
    def test_build_parser_returns_argparse(self):
        import argparse
        parser = build_parser()
        self.assertIsInstance(parser, argparse.ArgumentParser)

    def test_configure_logging_verbose(self):
        # Reset root logger handlers so basicConfig takes effect
        root_logger = logging.getLogger()
        for h in root_logger.handlers[:]:
            root_logger.removeHandler(h)
        configure_logging(verbose=True)
        self.assertEqual(root_logger.level, logging.DEBUG)

    def test_configure_logging_normal(self):
        root_logger = logging.getLogger()
        for h in root_logger.handlers[:]:
            root_logger.removeHandler(h)
        configure_logging(verbose=False)
        self.assertEqual(root_logger.level, logging.INFO)

    def test_list_versions_empty(self):
        work_dir = tempfile.mkdtemp()
        try:
            from casaos_gen.cli import main as cli_main
            rc = cli_main(["--list-versions", "--work-dir", work_dir])
            self.assertEqual(rc, 0)
        finally:
            shutil.rmtree(work_dir)

    def test_no_input_file_error(self):
        """main() should exit with error when no input_file is given for default stage."""
        from casaos_gen.cli import main as cli_main
        # parser.error() calls sys.exit(2), so we expect SystemExit
        with self.assertRaises(SystemExit) as ctx:
            cli_main(["--stage", "all"])
        self.assertNotEqual(ctx.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
