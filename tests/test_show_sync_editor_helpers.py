import importlib.util
import tempfile
import unittest
from pathlib import Path


_MODULE_PATH = Path(__file__).resolve().parents[1] / "show-sync-editor.py"
_SPEC = importlib.util.spec_from_file_location("show_sync_editor_module", _MODULE_PATH)
show_sync_editor = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(show_sync_editor)


class ShowSyncEditorHelperTests(unittest.TestCase):
    def test_apply_media_persistence_sets_absolute_media_path(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_root = Path(td)
            media_file = tmp_root / "clip.mov"
            media_file.write_bytes(b"mov")
            old_home = show_sync_editor._HOME
            try:
                show_sync_editor._HOME = str(tmp_root)
                data, last_video = show_sync_editor._apply_media_persistence(
                    {"media": {"src": "clip.mov", "path": ""}},
                    str(media_file),
                )
                self.assertEqual(data["media"]["path"], str(media_file.resolve()))
                self.assertEqual(last_video, str(media_file.resolve()))
            finally:
                show_sync_editor._HOME = old_home

    def test_apply_media_persistence_ignores_non_absolute_last_video(self):
        data, last_video = show_sync_editor._apply_media_persistence(
            {"media": {"src": "clip.mov", "path": "clip.mov"}},
            "clip.mov",
        )
        self.assertEqual(data["media"]["path"], "")
        self.assertEqual(last_video, "")

    def test_validate_directory_path_requires_home_containment(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_root = Path(td)
            home_dir = tmp_root / "home"
            other_dir = tmp_root / "outside"
            home_dir.mkdir(parents=True, exist_ok=True)
            other_dir.mkdir(parents=True, exist_ok=True)
            old_home = show_sync_editor._HOME
            try:
                show_sync_editor._HOME = str(home_dir.resolve())
                with self.assertRaisesRegex(ValueError, "Directory not allowed"):
                    show_sync_editor._validate_directory_path(str(other_dir.resolve()))
            finally:
                show_sync_editor._HOME = old_home

    def test_validate_directory_path_create_and_missing_behaviour(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_root = Path(td)
            home_dir = tmp_root / "home"
            home_dir.mkdir(parents=True, exist_ok=True)
            valid_dir = home_dir / "shows"
            missing_dir = home_dir / "missing"
            old_home = show_sync_editor._HOME
            try:
                show_sync_editor._HOME = str(home_dir.resolve())
                with self.assertRaisesRegex(ValueError, "Directory not found"):
                    show_sync_editor._validate_directory_path(str(missing_dir), create=False)
                created = show_sync_editor._validate_directory_path(str(valid_dir), create=True)
                self.assertEqual(created, str(valid_dir.resolve()))
                self.assertTrue(valid_dir.is_dir())
            finally:
                show_sync_editor._HOME = old_home


if __name__ == "__main__":
    unittest.main()
