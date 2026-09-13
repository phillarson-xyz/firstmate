"""Unit tests for offline toolchain checks and the reproducible dependency lock."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(os.environ.get("FIRSTMATE_ROOT", Path(__file__).resolve().parent.parent))
if not (ROOT / "nix/check_toolchain.py").exists():
    ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("check_toolchain", ROOT / "nix/check_toolchain.py")
assert SPEC is not None and SPEC.loader is not None
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


class ToolchainTests(unittest.TestCase):
    def test_versions_are_unambiguous(self):
        self.assertEqual(checker.version("treehouse v2.0.1"), (2, 0, 1))
        for bad in ("unknown", "1.2.3 / 2.3.4", "1.2"):
            with self.assertRaises(ValueError):
                checker.version(bad)

    def test_diagnostics_do_not_inherit_credentials_or_homes(self):
        with mock.patch.dict(os.environ, {"GH_TOKEN": "test-only", "FM_HOME": "/live", "PATH": "/tools"}, clear=True):
            env = checker.isolated_env(Path("/scratch"))
        self.assertNotIn("GH_TOKEN", env)
        self.assertNotIn("FM_HOME", env)
        self.assertEqual(env["HOME"], "/scratch")
        self.assertEqual(env["PATH"], "/tools")
        self.assertEqual(env["NO_MISTAKES_NO_UPDATE_CHECK"], "1")

    def test_version_mismatch_fails(self):
        with self.assertRaisesRegex(ValueError, "expected"):
            checker.check({"treehouse": "2.0.1"}, {}, runner=lambda *args: "2.0.0")

    def test_new_firstmate_floor_fails(self):
        with self.assertRaisesRegex(ValueError, "below Firstmate"):
            checker.check({"tasks-axi": "0.2.5"}, {}, runner=lambda *args: "0.2.5", floors={"tasks-axi": "0.3.0"})

    def test_missing_feature_fails(self):
        with self.assertRaisesRegex(ValueError, "missing --lease"):
            checker.check({}, {}, runner=lambda *args: "unrelated help")

    def test_features_pass(self):
        def runner(argv, env):
            return {"treehouse": "--lease", "update": "--archive-body", "mv": "[<id>...]"}.get(argv[1], "--lease")
        self.assertEqual(len(checker.check({}, {}, runner=runner)), len(checker.FEATURES))

    def test_failed_command_is_not_success(self):
        failure = subprocess.CompletedProcess(["tool"], 1, stdout="failed")
        with mock.patch.object(subprocess, "run", return_value=failure):
            with self.assertRaisesRegex(RuntimeError, "exited 1"):
                checker.run(["tool"], {"HOME": "/scratch"})

    def test_missing_floor_is_not_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bin").mkdir()
            (root / "bin/fm-bootstrap.sh").write_text("NO_MISTAKES_MIN=unknown\n")
            with self.assertRaisesRegex(ValueError, "NO_MISTAKES_MIN"):
                checker.firstmate_floors(root)

    def test_npm_lock_matches_exact_direct_pins(self):
        manifest = json.loads((ROOT / "nix/axi/package.json").read_text())
        lock = json.loads((ROOT / "nix/axi/package-lock.json").read_text())
        self.assertEqual(manifest["dependencies"], lock["packages"][""]["dependencies"])
        for name, pin in manifest["dependencies"].items():
            self.assertRegex(pin, r"^\d+\.\d+\.\d+$")
            self.assertEqual(lock["packages"][f"node_modules/{name}"]["version"], pin)
        for name, package in lock["packages"].items():
            if name:
                self.assertTrue(package["resolved"].startswith("https://registry.npmjs.org/"))
                self.assertTrue(package["integrity"].startswith("sha512-"))

    def test_release_pins_cover_upstream_platforms(self):
        releases = json.loads((ROOT / "nix/releases.json").read_text())
        platforms = {"aarch64-darwin", "x86_64-darwin", "aarch64-linux", "x86_64-linux"}
        for package in releases.values():
            self.assertRegex(package["licenseHash"], r"^[0-9a-f]{64}$")
            self.assertEqual(set(package["hashes"]), platforms)
            for checksum in package["hashes"].values():
                self.assertRegex(checksum, r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
