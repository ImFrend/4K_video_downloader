"""
Теги m4a без ffmpeg: что ставится в файл и как ведём себя, когда что-то не так.
Только stdlib (unittest), без сети.

    python tests/test_tagging.py -v
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import tagging

JPEG = b"\xff\xd8\xff\xe0" + b"\0" * 4000
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 4000


class Jpeg(unittest.TestCase):
    def test_recognises_jpeg_only(self):
        self.assertTrue(tagging.is_jpeg(JPEG))
        self.assertFalse(tagging.is_jpeg(PNG))
        self.assertFalse(tagging.is_jpeg(b"RIFFwebp"))
        self.assertFalse(tagging.is_jpeg(b""))


class ThumbnailUrls(unittest.TestCase):
    def test_largest_first_and_all_jpg(self):
        urls = tagging.thumbnail_urls("dQw4w9WgXcQ")
        self.assertEqual(len(urls), len(tagging.THUMBNAIL_NAMES))
        self.assertTrue(all(u.endswith(".jpg") for u in urls))
        self.assertTrue(all("dQw4w9WgXcQ" in u for u in urls))
        self.assertIn("maxresdefault", urls[0])


class FetchThumbnail(unittest.TestCase):
    """Сеть подменена: проверяем выбор, а не загрузку."""

    def _urlopen(self, answers):
        def fake(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else req
            name = url.rsplit("/", 1)[-1]
            data = answers.get(name)
            if data is None:
                raise OSError("нет такой обложки")
            return mock.MagicMock(
                __enter__=lambda s: mock.MagicMock(read=lambda: data),
                __exit__=lambda *a: False)
        return fake

    def test_takes_the_first_available(self):
        answers = {"hq720.jpg": JPEG}
        with mock.patch("urllib.request.urlopen", self._urlopen(answers)):
            self.assertEqual(tagging.fetch_thumbnail("vid"), JPEG)

    def test_skips_placeholders_and_non_jpeg(self):
        # YouTube на отсутствующий размер отвечает 200 и крошечной заглушкой
        answers = {"maxresdefault.jpg": b"\xff\xd8\xff" + b"\0" * 100,
                   "hq720.jpg": PNG,
                   "hqdefault.jpg": JPEG}
        with mock.patch("urllib.request.urlopen", self._urlopen(answers)):
            self.assertEqual(tagging.fetch_thumbnail("vid"), JPEG)

    def test_none_when_nothing_works(self):
        with mock.patch("urllib.request.urlopen", self._urlopen({})):
            self.assertIsNone(tagging.fetch_thumbnail("vid"))


class TagM4a(unittest.TestCase):
    def test_bad_file_does_not_raise(self):
        bad = Path(tempfile.mkdtemp()) / "x.m4a"
        bad.write_bytes(b"not an mp4 at all")
        ok, msg = tagging.tag_m4a(bad, title="T")
        self.assertFalse(ok)
        self.assertTrue(msg)                      # причина названа, а не пустая строка
        self.assertEqual(bad.read_bytes(), b"not an mp4 at all")   # файл не испорчен

    def test_missing_mutagen_is_reported_not_raised(self):
        missing = Path(tempfile.mkdtemp()) / "x.m4a"
        missing.write_bytes(b"\0")
        with mock.patch.dict(sys.modules, {"mutagen.mp4": None}):
            ok, msg = tagging.tag_m4a(missing, title="T")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
