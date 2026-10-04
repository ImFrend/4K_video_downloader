"""
Тесты очереди под приложение: у него нет экрана очереди, поэтому отработавшие
джобы не должны её забивать, а список, присланный посреди загрузки, должен
стартовать сам, когда она закончится.
Только stdlib (unittest), без сети и без реальных загрузок.

    python tests/test_grab_queue.py -v
"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from core.downloader import Playlist, Track
from web import server


class _FakeProbe:
    """Вместо DownloadManager: разбор ссылки без сети."""

    def probe(self, url, limit=None):
        return Playlist(tracks=[Track(title="T", url="u", id="id1", playlist_index=1)],
                        title="PL")


def _manager():
    mgr = server.JobManager()
    mgr.dm = _FakeProbe()
    mgr._counter = 100             # не пересекаться с id джобов, расставленных вручную
    return mgr


def _job(mgr, jid, url, status, auto_start=False):
    job = server.Job(jid, url)
    job.status = status
    job.auto_start = auto_start
    mgr.jobs.append(job)
    return job


def _wait_probed(mgr, jid):
    """add_url разбирает ссылку в фоновом потоке — дождаться его."""
    for _ in range(200):
        job = next(j for j in mgr.jobs if j.id == jid)
        if job.status != "probing":
            return job
        time.sleep(0.01)
    raise AssertionError("разбор ссылки не завершился")


class AddUrlAfterFinished(unittest.TestCase):
    def test_finished_jobs_do_not_fill_the_queue(self):
        mgr = _manager()
        for i in range(config.WEB_MAX_PLAYLISTS):
            _job(mgr, i + 1, f"http://x/{i}", "done" if i % 2 else "cancelled")
        jid, msg = mgr.add_url("http://x/new")
        self.assertIsNotNone(jid, msg)
        self.assertEqual(_wait_probed(mgr, jid).status, "ready")

    def test_unfinished_jobs_still_fill_the_queue(self):
        mgr = _manager()
        for i in range(config.WEB_MAX_PLAYLISTS):
            _job(mgr, i + 1, f"http://x/{i}", "ready")
        jid, msg = mgr.add_url("http://x/new")
        self.assertIsNone(jid)
        self.assertIn("очередь полна", msg)

    def test_same_url_again_after_it_finished(self):
        mgr = _manager()
        _job(mgr, 1, "http://x/mix", "done")
        jid, msg = mgr.add_url("http://x/mix")
        self.assertIsNotNone(jid, msg)
        _wait_probed(mgr, jid)

    def test_same_url_while_still_in_queue(self):
        mgr = _manager()
        _job(mgr, 1, "http://x/mix", "downloading")
        jid, msg = mgr.add_url("http://x/mix")
        self.assertIsNone(jid)
        self.assertEqual(msg, "уже в очереди")


class GrabWhileDownloading(unittest.TestCase):
    def _finish(self, auto_start):
        mgr = _manager()
        started = []
        mgr.start = lambda: started.append(True) or True
        _job(mgr, 1, "http://x/first", "done")
        _job(mgr, 2, "http://x/second", "ready", auto_start=auto_start)
        mgr.running = True
        mgr._finish_run()
        self.assertFalse(mgr.running)
        return started

    def test_grab_sent_mid_download_starts_when_queue_finishes(self):
        self.assertEqual(self._finish(auto_start=True), [True])

    def test_manually_added_job_keeps_waiting_for_the_button(self):
        self.assertEqual(self._finish(auto_start=False), [])

    def test_nothing_waiting_nothing_started(self):
        mgr = _manager()
        started = []
        mgr.start = lambda: started.append(True) or True
        _job(mgr, 1, "http://x/first", "done", auto_start=True)
        mgr.running = True
        mgr._finish_run()
        self.assertEqual(started, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
