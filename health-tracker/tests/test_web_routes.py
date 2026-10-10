"""Site paths: every internal link in the web app points to a page that exists, every old (Dutch) path redirects to
its English page, and the onboarding page ids are the same in the API and the web app (they are stored per user)."""

import re
from pathlib import Path

from api import onboarding

WEB = Path(__file__).resolve().parents[1] / "web"
APP = WEB / "app"
REDIRECTS = APP / "(redirects)"

# Old path -> new path. Keep in sync with "Old paths" in docs/DEVELOPMENT.md.
OLD_PATHS = {
    "/historie/": "/history/",
    "/historie/activiteit/": "/history/activity/",
    "/rondjes/": "/routes/",
    "/rondjes/rondje/": "/routes/route/",
    "/instellingen/": "/settings/",
    "/instellingen/koppelingen/": "/settings/connections/",
    "/instellingen/beheer/": "/settings/admin/",
    "/instellingen/zones/": "/settings/zones/",
    "/instellingen/agents/": "/settings/agents/",
    "/analyses/doelen/": "/analyses/goals/",
    "/analyses/profiel/": "/analyses/profile/",
    "/help/handleiding/": "/help/guide/",
    "/health/": "/dashboard/body/",
    "/health/over-time/": "/trends/recovery/",
}


def url_of(page: Path) -> str:
    parts = [p for p in page.parent.relative_to(APP).parts if not (p.startswith("(") and p.endswith(")"))]
    return "/" + "".join(f"{p}/" for p in parts)


def pages(exclude_redirects: bool = True) -> set[str]:
    return {url_of(p) for p in APP.rglob("page.tsx") if not (exclude_redirects and REDIRECTS in p.parents)}


def test_every_internal_link_points_to_a_page():
    known = pages()
    found = set()
    for f in [*WEB.glob("app/**/*.ts*"), *WEB.glob("components/**/*.ts*"), *WEB.glob("lib/**/*.ts*")]:
        if REDIRECTS in f.parents:
            continue
        for m in re.finditer(r"""["'`](/[a-z][a-z0-9/-]*/)(?:[?#][^"'`]*)?["'`]""", f.read_text()):
            if not m.group(1).startswith("/api/"):
                found.add((m.group(1), f.relative_to(WEB).as_posix()))
    assert len(found) > 20
    missing = sorted(x for x in found if x[0] not in known)
    assert not missing, f"links to pages that do not exist: {missing}"


def test_old_paths_redirect_to_their_english_page():
    known = pages()
    redirects = {url_of(p): p for p in REDIRECTS.rglob("page.tsx")}
    assert set(redirects) == set(OLD_PATHS)
    for old, new in OLD_PATHS.items():
        assert new in known and old not in known, old
        assert f'<Redirect to="{new}" />' in redirects[old].read_text(), old


def test_onboarding_page_ids_match_the_web_app():
    src = (WEB / "lib" / "onboarding.ts").read_text()
    block = src[src.index("export const PAGES"):]
    web = re.findall(r'\{ id: "([a-z]+)", href: "(/[a-z/]*)" \}', block)
    assert tuple(i for i, _ in web) == onboarding.PAGES
    assert all(href in pages() for _, href in web)
