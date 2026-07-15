import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from safety.checker import run_tlc


class TlcGraphDumpTests(unittest.TestCase):
    @patch("safety.checker.find_tla_tools_jar", return_value=Path("/tmp/tla2tools.jar"))
    @patch("safety.checker.subprocess.run")
    def test_tlc_command_requests_dot_dump_in_run_directory(self, run, _jar):
        run.return_value.returncode = 0
        run.return_value.stdout = "No error has been found"
        run.return_value.stderr = ""
        with TemporaryDirectory() as directory:
            root = Path(directory)
            result = run_tlc(root / "Model.tla", root / "Model.cfg", dot_path=root / "tlc_state_graph.dot")
        self.assertEqual(result.status, "passed")
        self.assertIn("-dump", result.command)
        self.assertIn("dot,actionlabels,colorize", result.command)
        self.assertIn("tlc_state_graph.dot", result.command)
