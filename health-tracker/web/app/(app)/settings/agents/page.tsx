"use client";

// Settings: access for coaching agents (Claude, ChatGPT, Codex, Gemini, Copilot or any other MCP client). The page is
// shared with wealth-tracker (packages/ui/src/account/AgentsPage.tsx); here only what is health's own, including the
// variables for tools/tr.py next to a new token.

import AgentsPage from "@trackerai/ui/account/AgentsPage";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { rich } from "@/lib/i18n/rich";

function Variables({ token, origin }: { token: string; origin: string }) {
  const t = useT();
  const value = `TRAINING_API_URL=${origin}\nTRAINING_API_TOKEN=${token}`;
  return (
    <div className="flex flex-col gap-1.5">
      <h3 className="text-[13px] font-semibold">{t.agents.cliTitle}</h3>
      <p className="text-[12.5px] text-ink-muted">
        {rich(t.agents.cliText, { code: () => <code className="font-mono text-[12px]">{origin.replace(/^https?:\/\//, "")}</code> })}
      </p>
      <span className="text-[12px] font-medium text-ink-muted">{t.agents.variables}</span>
      <code className="select-all whitespace-pre-wrap break-all rounded bg-[var(--surface-sunken)] px-2.5 py-1.5 font-mono text-[12px]">
        {value}
      </code>
    </div>
  );
}

export default function Agents() {
  const t = useT();
  return (
    <AgentsPage
      api={api}
      app="health"
      site="health-tracker"
      title={t.agents.title}
      intro={
        <>
          {t.agents.intro1} {t.agents.intro2}
        </>
      }
      levels={{ read: t.agents.levelRead, write: t.agents.levelWrite }}
      tokenExtra={(token, origin) => <Variables token={token} origin={origin} />}
    />
  );
}
