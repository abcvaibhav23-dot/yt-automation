import tempfile
import unittest
from pathlib import Path

from shorts_factory.src.subtitle_generator import SubtitleEntry
from shorts_factory.src.video_builder import _build_scene_clips, _build_subtitle_image


class VideoBuilderRegressionTests(unittest.TestCase):
    def test_subtitle_image_renders_expected_size(self) -> None:
        img = _build_subtitle_image("यह एक परीक्षण पंक्ति है", width=1080)
        self.assertEqual(img.size, (1080, 220))

    def test_scene_clips_generated_without_external_assets(self) -> None:
        subtitles = [
            SubtitleEntry(start=0.0, end=1.5, text="पहला दृश्य"),
            SubtitleEntry(start=1.5, end=3.0, text="दूसरा दृश्य"),
        ]
        with tempfile.TemporaryDirectory(prefix="vb_test_") as tmp:
            clips, external_count = _build_scene_clips(
                subtitles=subtitles,
                style="funny",
                region="mirzapur",
                size=(360, 640),
                cache_dir=Path(tmp),
                use_external_assets=False,
            )
            try:
                # one motion clip + one fx clip per subtitle
                self.assertEqual(len(clips), len(subtitles) * 2)
                self.assertEqual(external_count, 0)
            finally:
                for clip in clips:
                    clip.close()

    def test_synth_scene_image_contains_rendered_file(self) -> None:
        from shorts_factory.src.video_builder import _synthesize_scene_image

        with tempfile.TemporaryDirectory(prefix="vb_synth_") as tmp:
            out = _synthesize_scene_image(
                text="ऑफिस लेट पहुँचना वाला सीन",
                index=0,
                cache_dir=Path(tmp),
                size=(360, 640),
            )
            self.assertTrue(out.exists())
            self.assertGreater(out.stat().st_size, 1024)


if __name__ == "__main__":
    unittest.main()
