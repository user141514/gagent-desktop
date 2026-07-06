import importlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
LLM_CONFIG_PATH = PACKAGE_ROOT / "backend" / "core" / "api" / "llm_config.py"


class LlmConfigPathTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.appdata = Path(self.temp_dir.name) / "Roaming"
        self.appdata.mkdir(parents=True)
        self.old_env = {
            key: os.environ.get(key)
            for key in ("APPDATA", "GAGENT_DESKTOP_STATE_DIR", "GAGENT_CONFIG_DIR")
        }
        os.environ["APPDATA"] = str(self.appdata)
        os.environ.pop("GAGENT_DESKTOP_STATE_DIR", None)
        os.environ.pop("GAGENT_CONFIG_DIR", None)
        self.llm_config = load_llm_config_module()

    def tearDown(self):
        for key, value in self.old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temp_dir.cleanup()


def load_llm_config_module():
    module_name = "llm_config_under_test"
    spec = importlib.util.spec_from_file_location(module_name, LLM_CONFIG_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {LLM_CONFIG_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class LlmConfigPathBehaviorTest(LlmConfigPathTest):
    def test_windows_config_path_uses_gagent_desktop_appdata_dir(self):
        path = self.llm_config.get_config_path()

        self.assertEqual(path, self.appdata / "gagent-desktop" / "llm_config.json")

    def test_legacy_genericagent_config_is_migrated_to_gagent_desktop(self):
        legacy_path = self.appdata / "GenericAgent" / "llm_config.json"
        legacy_path.parent.mkdir(parents=True)
        legacy_path.write_text(
            json.dumps(
                {
                    "provider": "deepseek",
                    "api_key": "legacy-key",
                    "base_url": "https://legacy.example.com",
                    "model": "legacy-model",
                }
            ),
            encoding="utf-8",
        )

        config = self.llm_config.load_saved_llm_config()
        new_path = self.appdata / "gagent-desktop" / "llm_config.json"

        self.assertEqual(config["api_key"], "legacy-key")
        self.assertTrue(new_path.exists())
        self.assertEqual(json.loads(new_path.read_text(encoding="utf-8"))["model"], "legacy-model")


if __name__ == "__main__":
    unittest.main()
