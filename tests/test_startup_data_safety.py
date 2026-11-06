import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class StartupDataSafetyTest(unittest.TestCase):
    def test_import_does_not_rewrite_operational_json_by_default(self):
        repo = Path(__file__).resolve().parents[1]
        filenames = (
            "tickets.json",
            "stock.json",
            "stock_movimientos.json",
            "comprobantes.json",
        )

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            uploads_dir = Path(tmp) / "uploads"
            data_dir.mkdir()
            before = {}
            for filename in filenames:
                source = repo / "data" / filename
                destination = data_dir / filename
                shutil.copy2(source, destination)
                before[filename] = destination.read_bytes()

            env = os.environ.copy()
            env.pop("DATABASE_URL", None)
            env.pop("RENDER", None)
            env.pop("RUN_LEGACY_DEMO_DATA_TASKS", None)
            env["TECMAN_DATA_DIR"] = str(data_dir)
            env["TECMAN_UPLOADS_DIR"] = str(uploads_dir)
            result = subprocess.run(
                [sys.executable, "-c", "import app"],
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            for filename, original in before.items():
                self.assertEqual(
                    (data_dir / filename).read_bytes(),
                    original,
                    f"El arranque reescribió {filename}",
                )


if __name__ == "__main__":
    unittest.main()
