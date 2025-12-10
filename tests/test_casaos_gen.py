import unittest
from pathlib import Path

from casaos_gen import models
from casaos_gen.i18n import load_translation_map, wrap_multilang
from casaos_gen.parser import build_casaos_meta
from casaos_gen.yaml_out import build_final_compose


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
        self.assertIn("db", meta.services)
        self.assertEqual(meta.services["db"].ports[0].container, "5432")
        self.assertEqual(len(meta.services["web"].envs), 2)


class CasaOSI18NTests(unittest.TestCase):
    def test_wrap_multilang_uses_translation_table(self):
        translation_file = Path("casaos_gen/translations.yml")
        translations = load_translation_map(translation_file)
        wrapped = wrap_multilang(
            "Main web interface port",
            ["en_US", "zh_CN"],
            translation_map=translations,
        )
        self.assertEqual(wrapped["zh_CN"], "主 Web 界面端口")

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


if __name__ == "__main__":
    unittest.main()
