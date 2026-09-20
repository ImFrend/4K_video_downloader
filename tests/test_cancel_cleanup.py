"""
Тесты блока 2: cleanup хвостов и запись манифеста со статусом partial/complete.
Только stdlib (unittest), без сети и без реальных загрузок.

    python tests/test_cancel_cleanup.py -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.downloader import Track, _cleanup_partials, _reap_orphans
from core import library as lib
from web import server   # server.Job / server.JobManager._write_manifest


def rmtree(p):
    import shutil
    shutil.rmtree(p, ignore_errors=True)


class CleanupPartials(unittest.TestCase):
    def setUp(self):
        self.pl = Path(tempfile.mkdtemp())
        (self.pl / "01 - Song.m4a").write_bytes(b"\0" * 100)   # готовый — не трогать
        (self.pl / "02 - Song.m4a.part").write_bytes(b"\0")     # хвост
        (self.pl / "frag.ytdl").write_bytes(b"\0")              # хвост
        (self.pl / "cover.webp").write_bytes(b"\0")             # сырая обложка
        (self.pl / ".downloaded.txt").write_text("idx\n")       # архив — не трогать

    def tearDown(self):
        rmtree(self.pl)

    def test_removes_only_tails(self):
        n = _cleanup_partials(self.pl)
        self.assertEqual(n, 3)                                   # .part + .ytdl + .webp
        left = {p.name for p in self.pl.iterdir()}
        self.assertIn("01 - Song.m4a", left)                    # готовый цел
        self.assertIn(".downloaded.txt", left)                  # архив цел
        self.assertNotIn("02 - Song.m4a.part", left)

    def test_scoped_to_folder(self):
        # .part в СОСЕДНЕЙ папке не должен пострадать (glob, не rglob)
        sib = self.pl.parent / (self.pl.name + "_sib")
        sib.mkdir()
        (sib / "z.part").write_bytes(b"\0")
        try:
            _cleanup_partials(self.pl)
            self.assertTrue((sib / "z.part").exists())
        finally:
            rmtree(sib)


class ReapOrphans(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "A").mkdir()
        (self.root / "A" / "x.part").write_bytes(b"\0")
        (self.root / "B" / "deep").mkdir(parents=True)
        (self.root / "B" / "deep" / "y.ytdl").write_bytes(b"\0")
        (self.root / "A" / "01 - keep.m4a").write_bytes(b"\0")

    def tearDown(self):
        rmtree(self.root)

    def test_recursive_only_tails(self):
        n = _reap_orphans(self.root)
        self.assertEqual(n, 2)
        self.assertFalse((self.root / "A" / "x.part").exists())
        self.assertFalse((self.root / "B" / "deep" / "y.ytdl").exists())
        self.assertTrue((self.root / "A" / "01 - keep.m4a").exists())


class WriteManifest(unittest.TestCase):
    """_write_manifest не использует self → зовём как unbound с None."""

    def setUp(self):
        self.pl = Path(tempfile.mkdtemp())

    def tearDown(self):
        rmtree(self.pl)

    def _track(self, i, title, status, real=False):
        fp = ""
        if real:
            f = self.pl / f"{i:02d} - {title}.m4a"
            f.write_bytes(b"\0" * (i * 1000))
            fp = str(f)
        return Track(title=title, url="u", id=f"id{i}", playlist_index=i,
                     status=status, filepath=fp)

    def _write(self, tracks):
        job = server.Job(1, "http://mix")
        job.title = "PL"
        job.tracks = tracks
        server.JobManager._write_manifest(None, job, self.pl)
        return lib.load_manifest(self.pl)

    def test_partial(self):
        man = self._write([
            self._track(1, "A", "done", real=True),
            self._track(2, "B", "done", real=True),
            self._track(3, "C", "cancelled"),
        ])
        self.assertEqual(man["status"], lib.STATUS_PARTIAL)
        self.assertEqual(man["expected"], 3)
        self.assertEqual(man["source"], "http://mix")
        self.assertEqual(man["tracks"][2]["status"], "cancelled")
        self.assertIsNone(man["tracks"][2]["file"])             # у отменённого файла нет
        self.assertEqual(man["tracks"][0]["codec"], "aac")
        self.assertEqual(man["tracks"][0]["size"], 1000)
        self.assertEqual(man["tracks"][0]["id"], "id1")

    def test_complete(self):
        man = self._write([
            self._track(1, "A", "done", real=True),
            self._track(2, "B", "done", real=True),
        ])
        self.assertEqual(man["status"], lib.STATUS_COMPLETE)

    def test_all_cancelled(self):
        man = self._write([
            self._track(1, "A", "cancelled"),
            self._track(2, "B", "cancelled"),
        ])
        self.assertEqual(man["status"], lib.STATUS_CANCELLED)

    def test_preserves_created_on_rewrite(self):
        lib.save_manifest(self.pl, {"created": 12345, "tracks": []})
        man = self._write([self._track(1, "A", "done", real=True)])
        self.assertEqual(man["created"], 12345)                 # не перетёрли время


if __name__ == "__main__":
    unittest.main(verbosity=2)
