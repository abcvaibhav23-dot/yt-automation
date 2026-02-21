import unittest

from shorts_factory.src.tts_engine import VoiceConfig, _prepare_tts_text


class TtsPrepUnitTests(unittest.TestCase):
    def test_hindi_preprocessing_cleans_symbols_and_visual_tags(self) -> None:
        src = "[Close up] practical tech update 20% बढ़ेगा... API/AI @home"
        out = _prepare_tts_text(src, VoiceConfig(language="hi"))
        self.assertNotIn("[Close up]", out)
        self.assertIn("प्रैक्टिकल", out)
        self.assertIn("टेक", out)
        self.assertIn("20 प्रतिशत", out)
        self.assertIn("ए-पी-आई", out)
        self.assertIn("ए-आई", out)
        self.assertNotIn("/", out)

    def test_non_hindi_returns_cleaned_text_without_hindi_transform(self) -> None:
        src = "[Scene] Hello/World"
        out = _prepare_tts_text(src, VoiceConfig(language="en"))
        self.assertEqual(out, "Hello/World")


if __name__ == "__main__":
    unittest.main()
