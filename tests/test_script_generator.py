import os
import uuid
import unittest
from pathlib import Path

from shorts_factory.src.script_generator import generate_script


class ScriptGeneratorRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["OPENAI_PROMPTS_ENABLED"] = "0"

    def test_no_theme_input_metadata_in_generated_script(self) -> None:
        result = generate_script(
            style="funny",
            channel_name=f"UnitTest-{uuid.uuid4().hex[:8]}",
            scripts_dir=Path("shorts_factory/scripts"),
            region="mirzapur",
            persist=False,
        )
        self.assertNotIn("थीम इनपुट:", result.script_text)
        self.assertIn("नमस्ते दोस्तों", result.script_text)

    def test_consecutive_generation_is_not_identical(self) -> None:
        channel = f"UnitTest-{uuid.uuid4().hex[:8]}"
        first = generate_script(
            style="regional",
            channel_name=channel,
            scripts_dir=Path("shorts_factory/scripts"),
            region="bihar",
            persist=False,
        )
        second = generate_script(
            style="regional",
            channel_name=channel,
            scripts_dir=Path("shorts_factory/scripts"),
            region="bihar",
            persist=False,
        )
        self.assertNotEqual(first.script_text, second.script_text)


if __name__ == "__main__":
    unittest.main()
