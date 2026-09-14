#!/usr/bin/env python3
"""Offline CLI/feature checks, isolated from personal config and fleet state."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


FEATURES = (
    ("treehouse", ("get", "--help"), "--lease"),
    ("tasks-axi", ("update", "--help"), "--archive-body"),
    ("tasks-axi", ("mv", "--help"), "[<id>...]"),
)


def isolated_env(home):
    """Do not pass provider tokens or user config overrides to diagnostic CLIs."""
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "TMPDIR": str(home),
        "TMP": str(home),
        "TEMP": str(home),
        "XDG_CONFIG_HOME": str(home / "config"),
        "XDG_CACHE_HOME": str(home / "cache"),
        "XDG_DATA_HOME": str(home / "data"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "NPM_CONFIG_USERCONFIG": os.devnull,
        "NO_MISTAKES_NO_UPDATE_CHECK": "1",
        "NO_MISTAKES_TELEMETRY": "0",
        "CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS": "1",
        "NO_COLOR": "1",
        "TERM": "dumb",
        "LANG": "C.UTF-8",
    }


def run(argv, env):
    result = subprocess.run(
        argv, env=env, cwd=env["HOME"], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30,
    )
    if result.returncode:
        raise RuntimeError(f"{' '.join(argv)} exited {result.returncode}: {result.stdout.strip()}")
    return result.stdout.strip()


def version(text):
    matches = re.findall(r"(?<![\d.])(\d+)\.(\d+)\.(\d+)(?![\d.])", text)
    if len(matches) != 1:
        raise ValueError(f"expected one semantic version, got {text!r}")
    return tuple(map(int, matches[0]))


def firstmate_floors(root):
    """Read declared floors as data; never execute bootstrap or acquire a lock."""
    specs = {
        "bin/fm-bootstrap.sh": {
            "NO_MISTAKES_MIN": "no-mistakes",
            "GH_AXI_MIN": "gh-axi",
            "LAVISH_AXI_MIN": "lavish-axi",
        },
        "bin/fm-tasks-axi-lib.sh": {"FM_TASKS_AXI_MIN": "tasks-axi"},
        "bin/fm-quota-axi-lib.sh": {"FM_QUOTA_AXI_MIN": "quota-axi"},
    }
    floors = {}
    for path, keys in specs.items():
        text = (root / path).read_text()
        for key, tool in keys.items():
            matches = re.findall(rf"^{key}=(\d+\.\d+\.\d+)\s*$", text, re.MULTILINE)
            if len(matches) != 1:
                raise ValueError(f"cannot read unambiguous {key} from {root / path}")
            floors[tool] = matches[0]
    return floors


def check(versions, env, runner=run, floors=None):
    """A declared floor is only enforced if the toolchain pins that tool, so an
    unpinned floor is an error rather than a silently skipped comparison."""
    floors = floors or {}
    untracked = sorted(set(floors) - set(versions))
    if untracked:
        raise ValueError(f"floors declared for tools the toolchain does not pin: {', '.join(untracked)}")
    results = []
    for tool, expected in sorted(versions.items()):
        actual = runner([tool, "--version"], env)
        if version(actual) != version(expected):
            raise ValueError(f"{tool}: expected {expected}, got {actual!r}")
        minimum = floors.get(tool)
        if minimum and version(actual) < version(minimum):
            raise ValueError(f"{tool}: {actual!r} is below Firstmate floor {minimum}")
        results.append({"tool": tool, "version": expected, "ok": True})
    for tool, args, required in FEATURES:
        output = runner([tool, *args], env)
        if required not in output:
            raise ValueError(f"{tool} {' '.join(args)}: missing {required}")
        results.append({"tool": tool, "feature": required, "ok": True})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--firstmate-root", type=Path, required=True, help="compare against this checkout's version floors (read-only)")
    args = parser.parse_args()
    try:
        versions = json.loads(args.manifest.read_text())
        floors = firstmate_floors(args.firstmate_root.resolve())
        with tempfile.TemporaryDirectory(prefix="firstmate-toolchain-check-") as directory:
            results = check(versions, isolated_env(Path(directory)), floors=floors)
        print(json.dumps({"ok": True, "checks": results}, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
