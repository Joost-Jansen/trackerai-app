"use client";

import Card from "@trackerai/ui/components/Card";
import { useTr } from "@trackerai/ui/i18n";
import type { ReactNode } from "react";

const CLIENTS = ["claude", "openai", "copilot", "other"] as const;
export type AgentClient = (typeof CLIENTS)[number];
export const agentName = (client: AgentClient) => ({
  claude: "Claude", openai: "ChatGPT / Codex", copilot: "GitHub Copilot", other: "MCP",
})[client];

export default function AgentAssistant({ value, onChange, title, intro }: {
  value: AgentClient; onChange: (client: AgentClient) => void; title: string; intro: ReactNode;
}) {
  const tr = useTr();
  const labels = {
    claude: "Claude (app, claude.ai, Claude Code)",
    openai: "ChatGPT / Codex",
    copilot: "GitHub Copilot (VS Code, CLI)",
    other: tr("Another MCP client (Cursor, Gemini CLI, …)"),
  };
  return <Card title={title}>
    <p className="mb-4 max-w-prose text-[13px] leading-relaxed text-ink-muted">
      {intro}
    </p>
    <label className="flex flex-col gap-1.5">
      <span className="text-[12px] font-medium text-ink-muted">{tr("Assistant")}</span>
      <select className="ds-select h-9 w-full max-w-sm pl-2.5 text-[13px]"
        value={value} onChange={e => onChange(e.target.value as AgentClient)} aria-label={tr("Assistant")}>
        {CLIENTS.map(client => <option key={client} value={client}>{labels[client]}</option>)}
      </select>
    </label>
  </Card>;
}
