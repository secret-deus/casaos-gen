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


if __name__ == "__main__":
    unittest.main()
