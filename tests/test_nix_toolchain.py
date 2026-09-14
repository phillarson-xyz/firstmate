"""Unit tests for offline toolchain checks and the reproducible dependency lock."""
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
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

    def test_pinned_tool_below_its_declared_floor_fails(self):
        floors = checker.firstmate_floors(ROOT)
        self.assertIn("quota-axi", floors)
        major, minor, patch = checker.version(floors["quota-axi"])
        stale = f"{major}.{minor}.{patch - 1}"
        pinned = dict(floors, **{"quota-axi": stale})
        with self.assertRaisesRegex(ValueError, "quota-axi.*below Firstmate floor"):
            checker.check(pinned, {}, runner=lambda argv, env: pinned[argv[0]], floors=floors)

    def test_declared_floors_are_covered_by_the_pinned_toolchain(self):
        pins = json.loads((ROOT / "nix/axi/package.json").read_text())["dependencies"]
        pins.update(
            (tool, release["version"])
            for tool, release in json.loads((ROOT / "nix/releases.json").read_text()).items()
        )
        for tool, minimum in checker.firstmate_floors(ROOT).items():
            self.assertIn(tool, pins)
            self.assertGreaterEqual(checker.version(pins[tool]), checker.version(minimum))

    def test_floor_for_an_unpinned_tool_fails(self):
        with self.assertRaisesRegex(ValueError, "does not pin: ghost-axi"):
            checker.check({}, {}, runner=lambda *args: "--lease", floors={"ghost-axi": "1.0.0"})

    def test_darwin_date_keeps_the_bsd_epoch_contract_on_path(self):
        if platform.system() != "Darwin":
            self.skipTest("Firstmate only takes the BSD date branch when uname reports Darwin")
        env = {"PATH": os.environ.get("PATH", ""), "TZ": "UTC0"}
        epoch = 1700000000
        stamp = subprocess.run(
            ["date", "-r", str(epoch), "+%Y%m%d%H%M.%S"],
            env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        self.assertEqual(stamp.returncode, 0, stamp.stdout)
        with tempfile.TemporaryDirectory() as directory:
            beacon = Path(directory) / "last-watcher-beat"
            beacon.touch()
            touched = subprocess.run(
                ["touch", "-mt", stamp.stdout.strip(), str(beacon)],
                env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            self.assertEqual(touched.returncode, 0, touched.stdout)
            self.assertEqual(int(beacon.stat().st_mtime), epoch)

    def run_checker(self, argv, stubs=None):
        environment = dict(os.environ)
        if stubs is not None:
            environment["PATH"] = os.pathsep.join([str(stubs), environment.get("PATH", "")])
        return subprocess.run(
            [sys.executable, str(ROOT / "nix/check_toolchain.py"), *argv],
            env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    def stub_tools(self, directory, versions):
        stubs = Path(directory) / "stub-bin"
        stubs.mkdir()
        for tool, printed in versions.items():
            binary = stubs / tool
            binary.write_text(f"#!/bin/sh\necho '{tool} {printed}'\n")
            binary.chmod(0o755)
        return stubs

    def test_cli_refuses_to_report_success_without_a_firstmate_root(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "versions.json"
            manifest.write_text(json.dumps({}))
            done = self.run_checker(["--manifest", str(manifest)])
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(done.stdout, "")
        self.assertIn("--firstmate-root", done.stderr)

    def test_cli_enforces_declared_floors_against_an_explicit_root(self):
        floors = checker.firstmate_floors(ROOT)
        major, minor, patch = checker.version(floors["quota-axi"])
        pinned = dict(floors, **{"quota-axi": f"{major}.{minor}.{patch - 1}"})
        with tempfile.TemporaryDirectory() as directory:
            stubs = self.stub_tools(directory, pinned)
            manifest = Path(directory) / "versions.json"
            manifest.write_text(json.dumps(pinned))
            done = self.run_checker(
                ["--manifest", str(manifest), "--firstmate-root", str(ROOT)], stubs=stubs
            )
        self.assertEqual(done.returncode, 1, done.stderr)
        payload = json.loads(done.stdout)
        self.assertFalse(payload["ok"])
        self.assertRegex(payload["error"], r"quota-axi.*below Firstmate floor")

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
