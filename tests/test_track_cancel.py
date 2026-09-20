"""
Тесты потрековой отмены: точечная уборка хвостов одного трека, флаги отмены
в DownloadManager, ранний выход download_track и JobManager.cancel_track.
Только stdlib (unittest), без сети и без реальных загрузок.

    python tests/test_track_cancel.py -v
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.downloader import Track, DownloadManager, _cleanup_track_partials
from web import server


def rmtree(p):
    import shutil
    shutil.rmtree(p, ignore_errors=True)


class CleanupTrackPartials(unittest.TestCase):
    def setUp(self):
        self.pl = Path(tempfile.mkdtemp())
        (self.pl / "07 - X.m4a.part").write_bytes(b"\0")   # хвост трека 7
        (self.pl / "07 - X.webp").write_bytes(b"\0")        # сырая обложка трека 7
        (self.pl / "07 - X.m4a").write_bytes(b"\0" * 50)    # готовый трек 7 — не трогать
        (self.pl / "08 - Y.m4a.part").write_bytes(b"\0")   # СОСЕД качается — не трогать

    def tearDown(self):
        rmtree(self.pl)

    def test_removes_only_this_track_tails(self):
        n = _cleanup_track_partials(self.pl, 7)
        self.assertEqual(n, 2)                              # .part + .webp трека 7
        left = {p.name for p in self.pl.iterdir()}
        self.assertNotIn("07 - X.m4a.part", left)
        self.assertNotIn("07 - X.webp", left)
        self.assertIn("07 - X.m4a", left)                  # готовый цел
        self.assertIn("08 - Y.m4a.part", left)             # сосед цел

    def test_no_index_is_noop(self):
        self.assertEqual(_cleanup_track_partials(self.pl, None), 0)
        self.assertTrue((self.pl / "08 - Y.m4a.part").exists())


class ManagerCancelFlags(unittest.TestCase):
    def _t(self, i, vid):
        return Track(title=f"T{i}", url="u", id=vid, playlist_index=i)

    def test_by_id(self):
        dm = DownloadManager()
        t1, t2 = self._t(1, "vid1"), self._t(2, "vid2")
        dm.cancel_track("vid1")
        self.assertTrue(dm._track_cancelled(t1))
        self.assertFalse(dm._track_cancelled(t2))

    def test_by_index(self):
        dm = DownloadManager()
        t2 = self._t(2, "")                                 # без id → ключ по индексу
        self.assertFalse(dm._track_cancelled(t2))
        dm.cancel_track("#2")
        self.assertTrue(dm._track_cancelled(t2))

    def test_whole_job_cancels_all(self):
        dm = DownloadManager()
        t1, t2 = self._t(1, "vid1"), self._t(2, "vid2")
        dm.cancel()
        self.assertTrue(dm._track_cancelled(t1))
        self.assertTrue(dm._track_cancelled(t2))

    def test_empty_ident_ignored(self):
        dm = DownloadManager()
        dm.cancel_track("")                                 # ничего не должно отмениться
        self.assertFalse(dm._track_cancelled(self._t(1, "vid1")))


class DownloadTrackEarlyExit(unittest.TestCase):
    """Отменённый ДО старта трек не идёт в сеть — download_track выходит сразу."""

    def test_pending_cancelled_returns_immediately(self):
        dm = DownloadManager(output_dir=Path(tempfile.mkdtemp()))
        t = Track(title="A", url="http://example/x", id="vid1", playlist_index=1)
        dm.cancel_track("vid1")
        seen = []
        dm.download_track(t, lambda tr: seen.append(tr.status), subdir="PL")
        self.assertEqual(t.status, "cancelled")
        self.assertEqual(seen, ["cancelled"])              # ровно один emit, без сети


class JobManagerCancelTrack(unittest.TestCase):
    def _job(self, mgr, jid, n):
        job = server.Job(jid, "http://mix")
        job.title = "PL"
        job.tracks = [Track(title=f"T{i}", url="u", id=f"id{i}", playlist_index=i)
                      for i in range(1, n + 1)]
        mgr.jobs.append(job)
        return job

    def test_removes_one_keeps_rest(self):
        mgr = server.JobManager()
        job = self._job(mgr, 1, 3)
        self.assertTrue(mgr.cancel_track(1, 2))
        self.assertEqual([t.playlist_index for t in job.tracks], [1, 3])
        self.assertIn("id2", job.pre_cancel)               # запомнили для переигровки

    def test_unknown_index(self):
        mgr = server.JobManager()
        self._job(mgr, 1, 2)
        self.assertFalse(mgr.cancel_track(1, 99))

    def test_unknown_job(self):
        mgr = server.JobManager()
        self.assertFalse(mgr.cancel_track(777, 1))

    def test_empty_job_removed(self):
        mgr = server.JobManager()
        self._job(mgr, 1, 1)
        mgr.running = False
        self.assertTrue(mgr.cancel_track(1, 1))
        self.assertEqual(mgr.jobs, [])                      # микс опустел → убран


if __name__ == "__main__":
    unittest.main(verbosity=2)
