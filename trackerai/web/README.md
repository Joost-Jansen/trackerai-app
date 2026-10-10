# trackerai-web

trackerai.nl: the front door of the trackers (`FrontDoor` from [packages/marketing](../../packages/marketing)) with
login, sign-up and two-step login, and `/admin` (`Admin`), the admin page for every tracker. A Next 16 standalone
server; everything under `/api/*` goes to [trackerai-api](../api) (the account, the admin's tools and
`/api/hub/{app}/...` to each tracker's own admin API).

| Variable | When | What |
|---|---|---|
| `API_INTERNAL_URL` | build | Where `/api/*` goes: trackerai-api (`http://trackerai-api.railway.internal:8000` on Railway). Next fixes it at build time |
| `LANDING_HEALTH_URL`, `LANDING_WEALTH_URL` | run | Each tracker's address, for the links and the sign-up; a tracker without one is not offered |

```bash
npm ci                                   # once, at the repo root (one workspace, one lockfile)
cd trackerai/web && npm run dev          # http://localhost:3000; /api/* goes to localhost:8000
docker build -f trackerai/web/Dockerfile --build-arg API_INTERNAL_URL=http://trackerai-api:8000 .   # from the repo root
```
