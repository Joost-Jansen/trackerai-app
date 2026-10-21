"use client";

// Help, Claude as coach: what Claude can do with your data, how to connect it (MCP or tools/tr.py) and what to know
// about the token. The buttons and commands themselves are under Settings, Agents.

import Card from "@trackerai/ui/components/Card";
import { ButtonLink } from "@/components/ds";
import { A, Check, stepExplain } from "@/components/onboarding/steps";
import { useT } from "@/lib/i18n";
import { bold, rich } from "@/lib/i18n/rich";
import { useOnboarding } from "@/lib/onboarding";

export default function HelpClaude() {
  const t = useT();
  const c = t.help.claude;
  const o = useOnboarding().data ?? null;
  const ex = stepExplain("agent", o, t);
  const tokens = o?.status.agents.tokens ?? 0;
  const tags = {
    b: bold,
    code: (x: string) => <code className="font-mono text-[12px]">{x}</code>,
    link: (x: string) => <A href="/settings/agents/">{x}</A>,
    log: (x: string) => <A href="/log/">{x}</A>,
    plan: (x: string) => <A href="/plan/">{x}</A>,
  };

  return (
    <div className="flex flex-col gap-4">
      <Card
        title={c.title}
        action={
          <ButtonLink href="/settings/agents/" size="sm" variant={tokens ? "secondary" : "primary"}>
            {c.toAgents}
          </ButtonLink>
        }
      >
        <div className="flex max-w-[46rem] flex-col gap-3 text-[13.5px] leading-relaxed">
          <p>{ex.intro}</p>
          {o && (
            <p className="flex items-center gap-2 text-[13px]">
              <Check done={tokens > 0} size={18} />
              {tokens > 0 ? c.active(tokens) : c.none}
            </p>
          )}
        </div>
      </Card>

      <Card title={c.connect}>
        <ol className="flex max-w-[46rem] list-decimal flex-col gap-2 pl-5 text-[13.5px] leading-relaxed">
          {c.steps.map((s, i) => (
            <li key={i}>{rich(s, tags)}</li>
          ))}
        </ol>
      </Card>

      <Card title={c.good}>
        <ul className="flex max-w-[46rem] list-disc flex-col gap-1.5 pl-5 text-[13.5px] leading-relaxed">
          {c.notes.map((s, i) => (
            <li key={i}>{rich(s, tags)}</li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
