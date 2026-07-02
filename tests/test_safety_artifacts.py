import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from safety.artifacts import cleanup_old_safety_artifacts


class SafetyArtifactTests(unittest.TestCase):
    def test_cleanup_removes_old_run_dirs_and_preserves_fresh_dirs(self):
        now = 1_800_000_000.0
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            old_dir = root / "old-run"
            fresh_dir = root / "fresh-run"
            old_dir.mkdir()
            fresh_dir.mkdir()
            (old_dir / "report.json").write_text("{}\n", encoding="utf-8")
            (fresh_dir / "report.json").write_text("{}\n", encoding="utf-8")
            old_time = now - 25 * 60 * 60
            fresh_time = now - 2 * 60 * 60
            os.utime(old_dir, (old_time, old_time))
            os.utime(fresh_dir, (fresh_time, fresh_time))

            removed = cleanup_old_safety_artifacts(root, retention_hours=24, now=now)

            self.assertEqual(removed, [old_dir])
            self.assertFalse(old_dir.exists())
            self.assertTrue(fresh_dir.exists())


if __name__ == "__main__":
    unittest.main()
