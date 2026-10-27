"use client";

// Agents: let an AI assistant (Claude, ChatGPT, Codex, Gemini, Copilot or any other MCP client) read along and keep
// things up to date. The page is shared with health-tracker (packages/ui/src/account/AgentsPage.tsx); here only
// what is wealth's own. The server lives in backend/app/routers/mcp.py; what a token may do is in backend/app/deps.py.

import AgentsPage from "@trackerai/ui/account/AgentsPage";
import { api } from "@/lib/api";
import { tr } from "@/lib/i18n";

export default function Agents() {
  // The name of this site (stock-tracker or wealth-tracker), as in the browser tab.
  const site = (typeof document === "undefined" ? "" : document.title.split(/\s+[—-]\s+/)[0].trim()) || "wealth-tracker";
  return (
    <AgentsPage
      api={api}
      app="wealth"
      site={site}
      title={tr("Connect an AI assistant")}
      intro={tr(
        "An AI assistant (Claude, ChatGPT, Codex, Copilot, Gemini or any other MCP client) can view your portfolio, net worth and spending and, if you allow it, label transactions and manage budgets. Choose your assistant below to connect it. You can revoke its access here at any time.",
      )}
      levels={{
        read: tr("Read: view everything, change nothing."),
        write: tr(
          "Read and write: also label transactions, keep budgets, labelling rules, categories and settings, enter balances and add transactions. Never upload, delete transactions or accounts, bank connections or your account.",
        ),
      }}
    />
  );
}
