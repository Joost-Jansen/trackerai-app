"""The API image (api/Dockerfile) installs only api/requirements.txt. Everything api.main imports (also via tools/) must be listed there,
or the deploy crashes on start (happened once: cryptography was missing after the in-app Garmin sync was added)."""

import re
import subprocess
import sys
from importlib.metadata import packages_distributions
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def listed() -> set[str]:
    names = set()
    for line in (ROOT / "api" / "requirements.txt").read_text().splitlines():
        line = line.split("#")[0].strip()
        if line:
            names.add(re.split(r"[\[<>=~! ]", line, 1)[0].lower().replace("_", "-"))
    return names


def test_everything_the_web_app_imports_is_in_api_requirements():
    # garminconnect, fitdecode and the example seed are imported inside functions (login, FIT parsing, api/example.py); load them here too
    code = "import sys, api.main, api.connections, api.sync_runner, scripts.seed_demo, garminconnect, fitdecode; print('\\n'.join(sorted({m.split('.')[0] for m in sys.modules})))"
    top = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    dists = packages_distributions()
    needed = set()
    for mod in top:
        if mod in sys.stdlib_module_names or mod in ("api", "tools", "scripts", "__main__") or mod not in dists:
            continue
        needed.update(d.lower().replace("_", "-") for d in dists[mod])
    have = listed() | {"trackerai-accounts", "trackerai-websec"}  # from packages/ in this repository: the Dockerfile installs them
    # installed as dependencies of listed packages (not imported directly by our code) are fine to be absent
    from importlib.metadata import requires

    transitive, todo = set(), list(have)
    while todo:  # everything the listed packages pull in, recursively
        name = todo.pop()
        try:
            reqs = requires(name) or []
        except Exception:
            continue
        for req in reqs:
            if "extra ==" in req:
                continue
            dep = re.split(r"[\[<>=~!; ]", req, 1)[0].lower().replace("_", "-")
            if dep not in transitive:
                transitive.add(dep)
                todo.append(dep)
    missing = sorted(d for d in needed if d not in have and d not in transitive)
    assert not missing, f"add to api/requirements.txt: {missing}"
