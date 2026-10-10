"""
frontend/lib/format.ts must format numbers exactly like charts.fmt_eu.

Both render the same screen: Plotly figures arrive at the browser as JSON with
their labels already formatted by fmt_eu, and the React around them formats the
same figures' numbers with format.ts. Any disagreement shows up as two spellings
of one number, side by side — or worse, two different roundings of it.

This drives the real format.ts through node rather than restating its expected
output, so it fails when *either* side drifts. The traps it has caught:

  - Intl's `style: "currency"` puts U+00A0 between symbol and amount; fmt_eu
    does not, and puts the minus after the symbol ("€-19,31").
  - Intl rounds the shortest decimal representation, Python the exact binary
    value: 2.675 is really 2.67499...82, so Streamlit prints 2,67 where a naive
    port printed 2,68.
  - Python rounds halves to even (0.125 -> 0,12); Intl defaults to halfExpand.
  - toFixed drops the sign of -0.0, which real data holds (a closed position
    with no gain), and which fmt_eu prints as "-0,00".
"""

import json
import os
import pathlib
import random
import shutil
import struct
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from domain.portfolio.series import fmt_eu  # noqa: E402

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_FORMAT_TS = os.path.join(_REPO_ROOT, "frontend", "lib", "format.ts")
# Resolves "@/…" and extensionless imports in the app's modules, as Next does.
_TS_RESOLVE = pathlib.Path(_REPO_ROOT, "frontend", "scripts", "ts-resolve.mjs").as_uri()

# The (decimals, prefix, suffix, plus) combinations app.py actually calls fmt_eu
# with — `grep -oE 'fmt_eu\([^)]*\)' app.py` — so this tracks real usage rather
# than a guess at the API surface.
_VARIANTS = [
    {"decimals": 2, "prefix": "€"},
    {"decimals": 4, "prefix": "€"},
    {"decimals": 2, "prefix": "€", "plus": True},
    {"decimals": 2, "suffix": "%", "plus": True},
    {"decimals": 1, "suffix": "%", "plus": True},
    {"decimals": 1, "suffix": "%"},
    {"decimals": 1, "plus": True},
    {"decimals": 4},
    {"decimals": 2},
]

_DRIVER = """
import { fmtEu, fmtShares } from %(format_ts)s;
import { readFileSync } from "node:fs";
const cases = JSON.parse(readFileSync(%(cases)s, "utf8"));
console.log(JSON.stringify(cases.map((c) =>
  c.shares ? fmtShares(c.value) : fmtEu(c.value, c.opts)
)));
"""


def _values():
    """Amounts, rounding-boundary values, exact ties, and arbitrary doubles."""
    random.seed(20260717)  # fixed: a formatter regression should not depend on the day
    vals = [
        0.0, -0.0, 1.0, -1.0, 0.5, 10.0, 1234.5, 13363.06, 3422.78, -19.31,
        28.27, 271.74, 9940.28, 477.63, -0.01, 1234567.891, 123456789.123,
        # each of these printed differently before this test existed
        2.675, 1.005, 0.125, 0.375, 0.135, 0.00005,
    ]
    for _ in range(600):
        vals.append(round(random.uniform(-50000, 50000), random.choice([0, 1, 2, 3, 4, 6])))
    for _ in range(600):
        # sitting exactly on a rounding boundary is where the two disagree
        vals.append(random.randint(-100000, 100000) + random.choice([0.005, 0.0005, 0.125, 0.375, 0.625, 0.875, 0.05, 0.5]))
    for _ in range(300):
        vals.append(random.randint(-1000, 1000) + random.randint(1, 255) / 256)  # dyadic: exact ties
    for _ in range(300):
        f = struct.unpack("<d", struct.pack("<Q", random.getrandbits(64)))[0]
        if f == f and abs(f) != float("inf") and abs(f) < 1e18:
            vals.append(f)
    return vals


def _run_node(cases, tmp_path):
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(json.dumps(cases), encoding="utf-8")
    driver = tmp_path / "driver.mjs"
    driver.write_text(
        # as_uri(), not the bare path: an ESM import specifier must be a
        # file:// URL, and a Windows path ("C:\\...") makes Node read the drive
        # letter as an unsupported protocol. On POSIX this is the same path with
        # a file:// prefix, so one form works on both.
        _DRIVER
        % {
            "format_ts": json.dumps(pathlib.Path(_FORMAT_TS).as_uri()),
            "cases": json.dumps(str(cases_path)),
        },
        encoding="utf-8",
    )
    proc = subprocess.run(
        [shutil.which("node"), "--import", _TS_RESOLVE, str(driver)],
        capture_output=True,
        text=True,
        # Explicit, because text=True otherwise decodes with the platform
        # locale: on Windows that is cp1252, which turns node's UTF-8 "€"
        # (e2 82 ac) into three characters ("â‚¬") and made every euro-prefixed
        # case here look like a formatter mismatch.
        encoding="utf-8",
        timeout=120,
    )
    assert proc.returncode == 0, f"node failed:\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


needs_node = pytest.mark.skipif(
    shutil.which("node") is None or not os.path.exists(_FORMAT_TS),
    reason="needs node and frontend/lib/format.ts",
)


@needs_node
def test_fmt_eu_matches_format_ts(tmp_path):
    random.seed(20260717)
    cases = [{"value": v, "opts": random.choice(_VARIANTS)} for v in _values()]
    expected = [
        fmt_eu(c["value"], c["opts"].get("decimals", 2), c["opts"].get("prefix", ""),
               c["opts"].get("suffix", ""), c["opts"].get("plus", False))
        for c in cases
    ]
    actual = _run_node(cases, tmp_path)

    mismatches = [
        f"{c['value']!r} {c['opts']} -> python={e!r} ts={a!r}"
        for c, e, a in zip(cases, expected, actual) if e != a
    ]
    assert not mismatches, f"{len(mismatches)}/{len(cases)} differ:\n" + "\n".join(mismatches[:20])


@needs_node
def test_share_counts_match_python_g_format(tmp_path):
    """Share counts print via f"{v:g}", not fmt_eu — significant digits, no grouping."""
    vals = [0, 1, 10, 10.0, 0.5, 100, 1000, 100000, 1000000, 12345678, 0.001,
            0.00001, 123.456, 1.23456789, 2.5, 999999, 1000001, -5, -0.5, 0.125]
    cases = [{"value": v, "shares": True} for v in vals]
    expected = [f"{v:g}".replace(".", ",") for v in vals]
    actual = _run_node(cases, tmp_path)

    mismatches = [
        f"{v!r} -> python={e!r} ts={a!r}"
        for v, e, a in zip(vals, expected, actual) if e != a
    ]
    assert not mismatches, "\n".join(mismatches)
