import os
import tempfile
import unittest
from pathlib import Path

from shorts_factory.src.secrets_manager import get_secret, load_env_and_bind, missing_secrets


class SecretsManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._snapshot = dict(os.environ)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._snapshot)

    def test_alias_mapping_binds_canonical_names(self) -> None:
        with tempfile.TemporaryDirectory(prefix="env_test_") as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("CHATGPT_API_KEY=test-openai\nXI_API_KEY=test-xi\n", encoding="utf-8")
            load_env_and_bind(Path(tmp))
            self.assertEqual(get_secret("OPENAI_API_KEY"), "test-openai")
            self.assertEqual(get_secret("ELEVENLABS_API_KEY"), "test-xi")

    def test_missing_secrets_reports_expected(self) -> None:
        os.environ["OPENAI_API_KEY"] = "x"
        missing = missing_secrets(["OPENAI_API_KEY", "ELEVENLABS_API_KEY"])
        self.assertEqual(missing, ["ELEVENLABS_API_KEY"])


if __name__ == "__main__":
    unittest.main()
