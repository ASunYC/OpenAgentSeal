import tempfile
import unittest
import base64
from pathlib import Path
from unittest.mock import patch

from open_agent.app.runner.models import AgentRequest
from open_agent.app.runner.runner import AgentRunner
from open_agent.user_config import ModelConfig, UserConfigManager


class TestSmartRoutingConfig(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_dir = Path(self.temp_dir.name)
        self.config_file = self.config_dir / "open_agent.json"
        UserConfigManager._instances.clear()
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.dir_patch = patch.object(UserConfigManager, "CONFIG_DIR", self.config_dir)
        self.file_patch = patch.object(UserConfigManager, "CONFIG_FILE", self.config_file)
        self.dir_patch.start()
        self.file_patch.start()
        self.manager = UserConfigManager()

    def tearDown(self):
        self.dir_patch.stop()
        self.file_patch.stop()
        UserConfigManager._instances.clear()
        self.temp_dir.cleanup()

    def test_smart_routing_defaults_and_persistence(self):
        default_config = self.manager.get_smart_routing()

        self.assertFalse(default_config["enabled"])
        self.assertEqual(default_config["text_model_id"], "")
        self.assertEqual(default_config["vision_model_id"], "")

        saved = self.manager.update_smart_routing(
            {
                "enabled": True,
                "text_model_id": "model_text",
                "vision_model_id": "model_vision",
                "audio_model_id": "",
                "fallback_model_id": "model_text",
            }
        )

        self.assertTrue(saved["enabled"])
        self.assertEqual(saved["vision_model_id"], "model_vision")

        UserConfigManager._instances.clear()
        reopened = UserConfigManager()
        self.assertEqual(reopened.get_smart_routing()["fallback_model_id"], "model_text")

    def test_resolve_model_for_modality_uses_fallbacks(self):
        text_model = ModelConfig.create(
            name="text-model",
            display_name="Text Model",
            provider="openai",
            api_key="sk-text",
            base_url="https://example.test/v1",
            provider_type="openai",
        )
        vision_model = ModelConfig.create(
            name="vision-model",
            display_name="Vision Model",
            provider="openai",
            api_key="sk-vision",
            base_url="https://example.test/v1",
            provider_type="openai",
        )
        self.manager.add_model(text_model)
        self.manager.add_model(vision_model)
        self.manager.update_smart_routing(
            {
                "enabled": True,
                "text_model_id": text_model.id,
                "vision_model_id": vision_model.id,
                "fallback_model_id": text_model.id,
            }
        )

        self.assertEqual(self.manager.resolve_smart_model_id("text", "agent_model"), text_model.id)
        self.assertEqual(self.manager.resolve_smart_model_id("vision", "agent_model"), vision_model.id)
        self.assertEqual(self.manager.resolve_smart_model_id("audio", "agent_model"), text_model.id)

        self.manager.update_smart_routing({"enabled": False})
        self.assertEqual(self.manager.resolve_smart_model_id("vision", "agent_model"), "agent_model")

    def test_runner_extracts_image_attachments_as_vision_content(self):
        runner = AgentRunner()
        request = AgentRequest(
            session_id="session_1",
            messages=[
                {
                    "role": "user",
                    "content": "describe this",
                    "attachments": [
                        {
                            "id": "att_1",
                            "name": "image.png",
                            "mime_type": "image/png",
                            "data": "aW1hZ2U=",
                        }
                    ],
                }
            ],
        )

        display_text, agent_content, modality = runner._extract_user_input(request)

        self.assertEqual(display_text, "describe this")
        self.assertEqual(modality, "vision")
        self.assertIsInstance(agent_content, list)
        self.assertEqual(agent_content[0]["type"], "text")
        self.assertEqual(agent_content[1]["type"], "image")
        self.assertEqual(agent_content[1]["source"]["media_type"], "image/png")

    def test_runner_parses_file_attachments_as_text_context(self):
        runner = AgentRunner()
        request = AgentRequest(
            session_id="session_1",
            messages=[
                {
                    "role": "user",
                    "content": "summarize this file",
                    "attachments": [
                        {
                            "id": "att_1",
                            "name": "notes.txt",
                            "mime_type": "text/plain",
                            "data": base64.b64encode("hello from file".encode("utf-8")).decode("ascii"),
                        }
                    ],
                }
            ],
        )

        display_text, agent_content, modality = runner._extract_user_input(request)

        self.assertEqual(display_text, "summarize this file")
        self.assertEqual(modality, "text")
        self.assertIn("summarize this file", agent_content)
        self.assertIn("文件名：notes.txt", agent_content)
        self.assertIn("hello from file", agent_content)


if __name__ == "__main__":
    unittest.main()
