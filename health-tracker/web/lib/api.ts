// The shared fetch wrapper (@trackerai/ui/lib/api), with health-tracker's example data.

import { ApiError, createApi, createExampleData } from "@trackerai/ui/lib/api";

export { ApiError };

// Example data (api/example.py): what is personal never carries it: who you are, account, connections, tokens,
// feedback, admin, and the onboarding state that drives the walk itself. Switch it with `setExampleData`
// (lib/exampleData.ts); writes during it get 403 `example_read_only`.
const example = createExampleData([
  "/api/onboarding",
  "/api/me",
  "/api/account",
  "/api/auth",
  "/api/login",
  "/api/logout",
  "/api/register",
  "/api/connections",
  "/api/agent-tokens",
  "/api/feedback",
  "/api/admin",
  "/api/mcp",
]);

export const setExampleData = example.set;
export const exampleDataOn = example.isOn;
export const subscribeExampleData = example.subscribe;
export const exampleHeader = example.header;

export const api = createApi({ headers: example.header });
