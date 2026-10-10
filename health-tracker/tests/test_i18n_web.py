"""The site's translations: nl and en have the same keys, and converted pages have no hardcoded Dutch
(web/scripts/check-i18n.mjs). Needs node and `npm ci` in web/; skipped without them."""

import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "web"


@pytest.mark.skipif(not shutil.which("node") or not (WEB / "node_modules" / "typescript").exists(), reason="node or web/node_modules missing")
def test_translations_have_the_same_keys_and_no_hardcoded_dutch():
    r = subprocess.run(["node", "scripts/check-i18n.mjs"], cwd=WEB, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
