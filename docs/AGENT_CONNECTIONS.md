# Assistant connections:

Health and wealth use one authorization server in `packages/accounts`, the existing TrackerAI account and the
existing two-step login. `packages/ui` supplies both the consent screen and the connected-apps card. The apps
only translate an approved shared account into their own data key and enforce their own tool permissions.

From Agents, select the single **ChatGPT / Codex** dropdown option. Only that choice shows the shared account
connection panel and its plugin button. Other assistants show their own token setup; manual OpenAI configuration
remains under Advanced setup. The dropdown itself is shared between both apps.

Open the existing TrackerAI plugin in ChatGPT or Codex, add it and choose Connect. The assistant
opens TrackerAI's consent page. Users choose access separately for each tracker; approving wealth never gives
health access. Read-only is the default even when a client requests editing. Sharing health data requires an
additional explicit checkbox. Users can revoke either tracker's connection from either Agents page.

OpenAI's installation and consent screens still require user interaction. There is no silent installation or
secret in a plugin ZIP. Manually created tokens remain available in Advanced setup.

## Deployment configuration:

Set these non-secret variables identically on both API services:

- `ACCOUNTS_OAUTH_ISSUER`: the HTTPS origin serving the authorization server, login and `/connect` page. Use the
  wealth app origin for this deployment. The front-door host currently redirects app pages and must not be used.
- `ACCOUNTS_OAUTH_RESOURCES`: a JSON object with `health` and `wealth` keys and each app's exact public `/api/mcp`
  URL. These URLs are the token audiences, not the backend's internal service addresses.
- `AGENT_PLUGIN_URL`: the existing plugin's ChatGPT URL. Update that same plugin to include both MCP servers;
  keep its identity and visibility. No client secret, bearer header or personal token belongs in the package.

The existing `ACCOUNTS_DATABASE_URL`, session key, encryption key, cookie domain and two-step policy continue
unchanged. OAuth remains unavailable without a valid issuer and resources. Deploying creates five new tables
in the accounts database; no existing account or app data is changed.

Deploy both backends and frontends first, verify discovery and permission tests, then configure the variables
and update the existing private plugin. Confirm a real host connection for each tracker before considering
rollout complete. Do not merge, deploy or publish the plugin without Joost's production approval.

## Protocol and security:

- OAuthlib's authorization-code implementation checks the protocol and PKCE. Public clients register through
  RFC 7591, with authentication method `none`, and must send S256 PKCE. No password or implicit grants.
- RFC 8414 authorization-server discovery, RFC 9728 protected-resource metadata, and a Bearer challenge on MCP
  authentication failures advertise the same issuer to both clients.
- Exact registered redirect matching; HTTPS redirects or native-client HTTP loopback only. No metadata URL
  fetching, which avoids client-metadata SSRF. The consent screen shows the callback host and the account.
- RFC 8707 `resource` is required at authorization, code exchange and refresh. One grant covers one tracker.
- Codes expire in five minutes and work once; access tokens last one hour. Refresh tokens rotate, and reuse ends
  the grant. Connections expire absolutely after 90 days. Codes and tokens are stored only as SHA-256 hashes.
- Token validity includes account suspension/deletion, app membership/health consent, email verification,
  required two-step setup, the account's session version and revocation. Password or two-step changes invalidate
  prior connections through that version. Account deletion cascades through grants, codes and tokens.
- Cookie-authenticated approval and revocation require a configured public Origin. Public registration and
  token endpoints do not use browser cookies and have per-IP limits; the existing app body limits still apply.
- OAuth never provides admin permissions, token management, bank credentials or another user's data. Health
  OAuth works through MCP only. Wealth uses its existing read/bookkeeping write allowlist for MCP's internal API
  requests. OAuth credentials are never accepted in a URL.

The tests use disposable accounts and generated credentials. The shared suite exercises the complete HTTP
flow, incorrect PKCE, redirect/resource/client binding, cancellation, consent, replay, refresh, expiry and account
changes. Both apps have integration tests for data isolation and forbidden writes/admin tools. Existing legacy
agent tests continue to cover their previous behavior.
