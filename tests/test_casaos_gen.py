import unittest
import tempfile
from pathlib import Path

from casaos_gen import models
from casaos_gen.compose_normalize import normalize_compose_for_appstore
from casaos_gen.constants import CDN_BASE
from casaos_gen.i18n import load_translation_map, wrap_multilang
from casaos_gen.parser import build_casaos_meta
from casaos_gen.template_stage import build_params_skeleton, build_template_compose
from casaos_gen.yaml_out import build_final_compose, write_compose_file


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
        zh_desc = final["services"]["web"]["x-casaos"]["ports"][0]["description"]["zh_CN"]
        self.assertEqual(zh_desc, "主 Web 界面端口")


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
