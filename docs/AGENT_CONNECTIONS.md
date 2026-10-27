# Assistant connections:

Health and wealth use one authorization server in `packages/accounts`, the existing TrackerAI account and the
existing two-step login. `packages/ui` supplies the whole Agents page (`account/AgentsPage.tsx`) and the consent
screen (`account/AgentConsent.tsx`); each app only passes its name, its API and what read and write mean for its data.
The apps translate an approved shared account into their own data key and enforce their own tool permissions.

The Agents page, the same in both apps:

1. **Assistant**: Claude, ChatGPT / Codex, Gemini (Workspace, Gemini Enterprise), Gemini CLI, GitHub Copilot, or
   another MCP client.
2. **Sign in with your TrackerAI account** (OAuth, no token to copy), with the steps for that assistant:
   - Claude, ChatGPT, Codex, Gemini CLI, VS Code and any client that follows the MCP authorization spec register
     themselves (RFC 7591) as public clients with PKCE. They only need the server URL.
   - Gemini in a work account asks for a client ID and secret. The page makes an **owned client**: one per tracker,
     for this account only, with Gemini's callback `https://vertexaisearch.cloud.google.com/oauth-redirect`. It shows
     the server URL, authorization URL, token URL, client ID, the secret (once) and the scopes to paste into Gemini.
   - The personal Gemini app cannot add your own MCP servers; the page points to Gemini CLI.
3. **Connected**: every approved connection and every owned client, each with a button to end it.
4. **Advanced setup: tokens**, for a client that cannot sign in and for scripts: read-only unless write is chosen,
   with an end date unless none is chosen. Health and wealth tokens behave the same (`/api/agent-tokens` answers
   `{"tokens": [...], "scopes": [...]}`); a read-only health token can only use GET outside MCP.

Users choose access separately for each tracker; approving wealth never gives health access. Read-only is the
default even when a client requests editing. Sharing health data requires an additional explicit checkbox. When a
client does not say which tracker (no `resource`, no tracker in its scopes), the consent screen asks.

Every MCP tool carries annotations (`readOnlyHint`, `destructiveHint`, `openWorldHint`) from
`trackerai_accounts.mcp_tools.describe`, so assistants can ask before a change; Gemini Enterprise asks for
confirmation on destructive tools.

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
  RFC 7591, with authentication method `none`, and must send S256 PKCE; a public client that sends a secret is
  refused. Owned clients always authenticate with their secret (`client_secret_basic` or `client_secret_post`);
  PKCE is optional for them and checked when used. Only the SHA-256 hash of a secret is stored; removing an owned
  client empties it, so no secret matches, and revokes its grants. An owned client works for its own account only.
  No password or implicit grants.
- RFC 8414 authorization-server discovery, RFC 9728 protected-resource metadata, and a Bearer challenge on MCP
  authentication failures advertise the same issuer to both clients.
- Exact registered redirect matching; HTTPS redirects or native-client HTTP loopback only. No metadata URL
  fetching, which avoids client-metadata SSRF. The consent screen shows the callback host and the account.
- RFC 8707 `resource` decides the tracker; without one, it comes from the owned client, from the one tracker the
  scopes name, or from the consent screen. A sent resource must match the grant at code exchange and refresh. Asking
  for two trackers at once is refused: one grant covers one tracker. Unknown scopes (`openid`, …) are ignored.
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
