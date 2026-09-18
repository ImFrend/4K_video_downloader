"""
Тесты core/library.py — модель Библиотеки. Только stdlib (unittest), без сети:
всё на временных папках/файлах. Запуск:

    python tests/test_library.py -v
    (или)  python -m unittest -v tests.test_library
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import library as lib


def touch_track(folder: Path, index: int, title: str, size: int = 1000, ext: str = "m4a") -> Path:
    """Создать файл трека вида `NN - Title.ext` заданного размера."""
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"{index:02d} - {title}.{ext}"
    p.write_bytes(b"\0" * size)
    return p


class ReconcileLegacyFolder(unittest.TestCase):
    """Папка с файлами, но без манифеста (легаси / другая версия)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.pl = self.tmp / "My Mix"
        touch_track(self.pl, 1, "Alpha", 2000)
        touch_track(self.pl, 2, "Beta", 3000)
        touch_track(self.pl, 3, "Gamma", 4000)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_builds_ordered_complete(self):
        man = lib.reconcile(self.pl)
        self.assertEqual([t["title"] for t in man["tracks"]], ["Alpha", "Beta", "Gamma"])
        self.assertEqual(man["status"], lib.STATUS_COMPLETE)
        self.assertTrue(all(t["status"] == "done" for t in man["tracks"]))
        self.assertTrue(all(t["id"] is None for t in man["tracks"]))  # id с диска не восстановить

    def test_adopts_manifest_on_disk(self):
        self.assertIsNone(lib.load_manifest(self.pl))
        lib.reconcile(self.pl, adopt=True)
        self.assertIsNotNone(lib.load_manifest(self.pl))  # усыновлено

    def test_no_adopt_leaves_disk_clean(self):
        lib.reconcile(self.pl, adopt=False)
        self.assertIsNone(lib.load_manifest(self.pl))


class ReconcileTrustsFreshManifest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.pl = self.tmp / "Snapshot"
        f1 = touch_track(self.pl, 1, "Song One")
        f2 = touch_track(self.pl, 2, "Song Two")
        lib.save_manifest(self.pl, {
            "title": "Мой снимок", "source": "snapshot", "expected": 2,
            "tracks": [
                {"id": "aaaaaaaaaaa", "file": f1.name, "title": "Song One",
                 "index": 1, "duration": 200, "codec": "aac", "status": "done"},
                {"id": "bbbbbbbbbbb", "file": f2.name, "title": "Song Two",
                 "index": 2, "duration": 150, "codec": "aac", "status": "done"},
            ],
        })

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_preserves_ids_and_metadata(self):
        man = lib.reconcile(self.pl)
        self.assertEqual(man["title"], "Мой снимок")
        self.assertEqual(man["source"], "snapshot")
        self.assertEqual([t["id"] for t in man["tracks"]], ["aaaaaaaaaaa", "bbbbbbbbbbb"])
        self.assertEqual(man["tracks"][0]["duration"], 200)
        self.assertEqual(man["status"], lib.STATUS_COMPLETE)

    def test_rebuilds_when_file_removed_out_of_band(self):
        # удалили файл мимо приложения → манифест устарел → пересборка
        (self.pl / "02 - Song Two.m4a").unlink()
        man = lib.reconcile(self.pl)
        self.assertEqual(len(man["tracks"]), 1)
        self.assertEqual(man["tracks"][0]["file"], "01 - Song One.m4a")


class PartialPlaylist(unittest.TestCase):
    """Отмена/ошибка на середине: манифест знает expected и хранит отменённый трек."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.pl = self.tmp / "Partial"
        f1 = touch_track(self.pl, 1, "Done A")
        f2 = touch_track(self.pl, 2, "Done B")
        lib.save_manifest(self.pl, {
            "title": "Partial", "expected": 3,
            "tracks": [
                {"id": "a", "file": f1.name, "title": "Done A", "index": 1, "status": "done"},
                {"id": "b", "file": f2.name, "title": "Done B", "index": 2, "status": "done"},
                {"id": "c", "file": "03 - Cancelled C.m4a", "title": "Cancelled C",
                 "index": 3, "status": "cancelled"},
            ],
        })

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_status_partial_and_keeps_cancelled(self):
        man = lib.reconcile(self.pl)
        self.assertEqual(man["status"], lib.STATUS_PARTIAL)
        self.assertEqual(len(man["tracks"]), 3)
        self.assertEqual(man["tracks"][2]["status"], "cancelled")

    def test_detail_numbers_all_sequentially(self):
        d = lib.detail(self.tmp, "Partial")
        self.assertEqual([t["n"] for t in d["tracks"]], [1, 2, 3])
        self.assertEqual(d["count"], 2)  # done


class DynamicNumbering(unittest.TestCase):
    """Ядро требования: номер в UI = позиция, НЕ имя файла."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.pl = self.tmp / "Gap"
        # на диске остались 01, 02, 04 (трек 03 удалён) — дыра в именах файлов
        touch_track(self.pl, 1, "First")
        touch_track(self.pl, 2, "Second")
        touch_track(self.pl, 4, "Fourth")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_ui_numbers_are_contiguous(self):
        d = lib.detail(self.tmp, "Gap")
        self.assertEqual([t["n"] for t in d["tracks"]], [1, 2, 3])            # UI: без дыр
        self.assertEqual([t["file"][:2] for t in d["tracks"]], ["01", "02", "04"])  # файлы: как есть


class DeriveStatus(unittest.TestCase):
    def test_variants(self):
        done = [{"status": "done"}, {"status": "done"}]
        self.assertEqual(lib.derive_pl_status(done), lib.STATUS_COMPLETE)
        self.assertEqual(lib.derive_pl_status(done, expected=3), lib.STATUS_PARTIAL)
        self.assertEqual(lib.derive_pl_status([{"status": "cancelled"}]), lib.STATUS_CANCELLED)
        self.assertEqual(lib.derive_pl_status([]), lib.STATUS_CANCELLED)


class ScanLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        touch_track(self.tmp / "Mix A", 1, "x")
        touch_track(self.tmp / "Mix B", 1, "y")
        touch_track(self.tmp / "Mix B", 2, "z")
        # чужая папка без наших файлов — не должна попасть
        (self.tmp / "Random").mkdir()
        (self.tmp / "Random" / "note.txt").write_text("hi")
        # разные времена → проверка сортировки «свежие сверху»
        os.utime(self.tmp / "Mix A", (1000, 1000))
        os.utime(self.tmp / "Mix B", (2000, 2000))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_filters_and_sorts(self):
        pls = lib.scan_library(self.tmp)
        keys = [p["key"] for p in pls]
        self.assertIn("Mix A", keys)
        self.assertIn("Mix B", keys)
        self.assertNotIn("Random", keys)          # чужую папку отсекли
        self.assertEqual(keys[0], "Mix B")         # новее → выше
        b = next(p for p in pls if p["key"] == "Mix B")
        self.assertEqual(b["count"], 2)


class PathTraversalGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        touch_track(self.tmp / "Safe", 1, "ok")
        (self.tmp.parent / "secret_marker").write_text("nope")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_rejects_escape(self):
        self.assertIsNotNone(lib.resolve_folder(self.tmp, "Safe"))
        self.assertIsNone(lib.resolve_folder(self.tmp, "../"))
        self.assertIsNone(lib.resolve_folder(self.tmp, "../.."))
        self.assertIsNone(lib.resolve_folder(self.tmp, "nonexistent"))
        self.assertIsNone(lib.detail(self.tmp, "../"))


class DeleteTrack(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.pl = self.tmp / "PL"
        f1 = touch_track(self.pl, 1, "A")
        f2 = touch_track(self.pl, 2, "B")
        f3 = touch_track(self.pl, 3, "C")
        (self.pl / lib.ARCHIVE_NAME).write_text("ida\nidb\nidc\n", encoding="utf-8")
        lib.save_manifest(self.pl, {
            "title": "PL", "expected": 3,
            "tracks": [
                {"id": "ida", "file": f1.name, "title": "A", "index": 1, "status": "done"},
                {"id": "idb", "file": f2.name, "title": "B", "index": 2, "status": "done"},
                {"id": "idc", "file": f3.name, "title": "C", "index": 3, "status": "done"},
            ],
        })

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_delete_by_id_removes_file_archive_manifest(self):
        res = lib.delete_track(self.tmp, "PL", "idb")
        self.assertTrue(res["ok"])
        self.assertTrue(res["deleted"].endswith("02 - B.m4a"))
        self.assertFalse((self.pl / "02 - B.m4a").exists())            # файл удалён
        ids = (self.pl / lib.ARCHIVE_NAME).read_text().split()
        self.assertNotIn("idb", ids)                                    # id из архива убран
        self.assertIn("ida", ids)
        man = lib.load_manifest(self.pl)
        self.assertEqual([t["id"] for t in man["tracks"]], ["ida", "idc"])
        # осознанное удаление из полного плейлиста → остаётся complete, не partial
        self.assertEqual(man["expected"], 2)
        self.assertEqual(man["status"], lib.STATUS_COMPLETE)

    def test_delete_by_filename(self):
        res = lib.delete_track(self.tmp, "PL", "01 - A.m4a")
        self.assertTrue(res["ok"])
        self.assertFalse((self.pl / "01 - A.m4a").exists())

    def test_ui_renumbers_after_delete(self):
        lib.delete_track(self.tmp, "PL", "idb")                          # удалили средний
        d = lib.detail(self.tmp, "PL")
        self.assertEqual([t["n"] for t in d["tracks"]], [1, 2])         # UI: 1,2 (без дыры)
        self.assertEqual([t["title"] for t in d["tracks"]], ["A", "C"])
        self.assertEqual([t["file"][:2] for t in d["tracks"]], ["01", "03"])  # файлы как есть

    def test_delete_unknown_returns_none(self):
        self.assertIsNone(lib.delete_track(self.tmp, "PL", "zzz"))
        self.assertIsNone(lib.delete_track(self.tmp, "NoSuch", "ida"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
