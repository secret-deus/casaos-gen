import unittest
from types import SimpleNamespace

from casaos_gen import models
from casaos_gen.llm_stage1 import run_stage1_llm


class FakeStage1Client:
    def __init__(self, responses):
        self.responses = responses
        self.prompts = []
        self.chat = SimpleNamespace(completions=self)

    def create(self, model, messages, temperature, max_tokens=None):
        prompt = messages[0]["content"]
        self.prompts.append(prompt)
        for marker, payload in self.responses.items():
            if marker in prompt:
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=payload))]
                )
        raise AssertionError(f"Unexpected Stage 1 prompt: {prompt}")


class Stage1LLMDecompositionTests(unittest.TestCase):
    def test_run_stage1_llm_refills_generated_placeholders_field_by_field(self):
        meta = models.CasaOSMeta(
            app=models.AppMeta(
                title="demo",
                tagline="demo on CasaOS",
                description=(
                    "demo is a self-hosted application stack deployed via Docker Compose.\n\n"
                    "Key Features:\n"
                    "- Runs multiple services as a single stack.\n"
                    "- Supports persistent storage and environment configuration.\n"
                    "- Ready to be imported and managed in CasaOS.\n"
                ),
                category="Utilities",
                author="me",
                main="demo",
                port_map="8080",
            ),
            services={
                "demo": models.ServiceMeta(
                    envs=[models.EnvItem(container="TZ", description="Environment variable TZ")],
                    ports=[models.PortItem(container="8080", description="Port 8080")],
                    volumes=[models.VolumeItem(container="/data", description="Volume /data")],
                )
            },
        )
        client = FakeStage1Client(
            {
                "Fill only the app.tagline field.": '{"tagline":"Better demo tagline"}',
                "Fill only the app.description paragraph 1 section.": '{"paragraph":"Paragraph 1."}',
                "Fill only the app.description paragraph 2 section.": '{"paragraph":"Paragraph 2."}',
                "Fill only the app.description paragraph 3 section.": '{"paragraph":"Paragraph 3."}',
                "Fill only the app.description key features section.": (
                    '{"items":["Fast setup","CasaOS friendly"]}'
                ),
                "Fill only the app.description learn more section.": (
                    '{"items":["[Official Website](https://example.com)"]}'
                ),
                'environment variable "TZ"': '{"description":"Sets the container timezone."}',
                'container port "8080"': '{"description":"Main web interface port."}',
                'container path "/data"': '{"description":"Stores persistent application data."}',
            }
        )

        out = run_stage1_llm(meta, model="fake-model", client=client)

        self.assertEqual(out.app.title, "demo")
        self.assertEqual(out.app.tagline, "Better demo tagline")
        self.assertIn("**Key Features:**", out.app.description)
        self.assertEqual(out.services["demo"].envs[0].description, "Sets the container timezone.")
        self.assertEqual(out.services["demo"].ports[0].description, "Main web interface port.")
        self.assertEqual(
            out.services["demo"].volumes[0].description,
            "Stores persistent application data.",
        )
        self.assertIn("Paragraph 1.", out.app.description)
        self.assertIn("Paragraph 2.", out.app.description)
        self.assertIn("Paragraph 3.", out.app.description)
        self.assertIn("- Fast setup", out.app.description)
        self.assertIn("- [Official Website](https://example.com)", out.app.description)
        self.assertEqual(len(client.prompts), 9)
        self.assertFalse(any("Fill only the app.title field." in prompt for prompt in client.prompts))

    def test_run_stage1_llm_preserves_existing_user_text(self):
        meta = models.CasaOSMeta(
            app=models.AppMeta(
                title="My App",
                tagline="Keep this tagline",
                description="Keep this description",
                category="Utilities",
                author="me",
                main="web",
                port_map="8080",
            ),
            services={
                "web": models.ServiceMeta(
                    envs=[models.EnvItem(container="TZ", description="Keep env description")],
                    ports=[models.PortItem(container="8080", description="")],
                    volumes=[models.VolumeItem(container="/data", description="Keep volume description")],
                )
            },
        )
        client = FakeStage1Client(
            {'container port "8080"': '{"description":"Main web interface port."}'}
        )

        out = run_stage1_llm(meta, model="fake-model", client=client, only_fill_empty=True)

        self.assertEqual(out.app.tagline, "Keep this tagline")
        self.assertEqual(out.app.description, "Keep this description")
        self.assertEqual(out.services["web"].envs[0].description, "Keep env description")
        self.assertEqual(out.services["web"].ports[0].description, "Main web interface port.")
        self.assertEqual(out.services["web"].volumes[0].description, "Keep volume description")
        self.assertEqual(len(client.prompts), 1)

    def test_run_stage1_llm_restores_fallback_when_field_response_is_blank(self):
        meta = models.CasaOSMeta(
            app=models.AppMeta(
                title="demo",
                tagline="demo on CasaOS",
                description=(
                    "demo is a self-hosted application stack deployed via Docker Compose.\n\n"
                    "Key Features:\n"
                    "- Runs multiple services as a single stack.\n"
                    "- Supports persistent storage and environment configuration.\n"
                    "- Ready to be imported and managed in CasaOS.\n"
                ),
                category="Utilities",
                author="me",
                main="demo",
                port_map="8080",
            ),
            services={
                "demo": models.ServiceMeta(
                    volumes=[models.VolumeItem(container="/data", description="Volume /data")]
                )
            },
        )
        client = FakeStage1Client(
            {
                "Fill only the app.tagline field.": '{"tagline":"Refilled tagline"}',
                "Fill only the app.description paragraph 1 section.": '{"paragraph":"Refilled paragraph 1"}',
                "Fill only the app.description paragraph 2 section.": '{"paragraph":"Refilled paragraph 2"}',
                "Fill only the app.description paragraph 3 section.": '{"paragraph":"Refilled paragraph 3"}',
                "Fill only the app.description key features section.": '{"items":["Feature A","Feature B"]}',
                "Fill only the app.description learn more section.": '{"items":["[Docs](https://example.com)"]}',
                'container path "/data"': '{"description":""}',
            }
        )

        out = run_stage1_llm(meta, model="fake-model", client=client)

        self.assertEqual(out.app.tagline, "Refilled tagline")
        self.assertIn("Refilled paragraph 1", out.app.description)
        self.assertIn("**Key Features:**", out.app.description)
        self.assertEqual(out.services["demo"].volumes[0].description, "Volume /data")


if __name__ == "__main__":
    unittest.main()
