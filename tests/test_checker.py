import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from safety.checker import (
    find_tla_tools_jar,
    parse_tlc_counterexample_history,
    parse_tlc_statistics,
    run_tlc,
)


class TlcRunnerTests(unittest.TestCase):
    def test_parses_branching_statistics_and_counterexample(self):
        output = """
/\\ history = <<"A", "A", "D", "Final settlement">>
87,382 states generated, 87,382 distinct states found, 65,535 states left on queue.
The depth of the complete state graph search is 10.
"""
        self.assertEqual(
            parse_tlc_statistics(output),
            {
                "states_generated": 87382,
                "distinct_states": 87382,
                "states_left": 65535,
                "search_depth": 10,
            },
        )
        self.assertEqual(
            parse_tlc_counterexample_history(output),
            ["A", "A", "D", "Final settlement"],
        )

    def test_finds_jar_from_tlaplus_vscode_extension(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            jar = root / ".vscode/extensions/tlaplus.vscode-ide-2026.5/tools/tla2tools.jar"
            jar.parent.mkdir(parents=True)
            jar.touch()

            with patch.dict("os.environ", {}, clear=True), patch(
                "safety.checker.Path.home", return_value=root
            ):
                self.assertEqual(find_tla_tools_jar(), jar)

    @patch("safety.checker.find_tla_tools_jar", return_value=Path("/tmp/tla2tools.jar"))
    @patch("safety.checker.subprocess.run")
    def test_tlc_runs_the_generated_model_in_its_artifact_directory(self, run, _jar):
        run.return_value.returncode = 0
        run.return_value.stdout = "No error has been found"
        run.return_value.stderr = ""

        with TemporaryDirectory() as directory:
            root = Path(directory)
            result = run_tlc(root / "Model.tla", root / "Model.cfg", timeout_seconds=7)

        self.assertEqual(result.status, "passed")
        self.assertEqual(
            result.command,
            [
                "java",
                "-cp",
                "/tmp/tla2tools.jar",
                "tlc2.TLC",
                "-config",
                "Model.cfg",
                "Model.tla",
            ],
        )
        self.assertEqual(run.call_args.kwargs["cwd"], root)
        self.assertEqual(run.call_args.kwargs["timeout"], 7)


if __name__ == "__main__":
    unittest.main()
