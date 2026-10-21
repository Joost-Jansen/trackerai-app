"use client";

// At the top of To label: how far you are, and what Claude can do for you. One
// button checks everything — what is still open, what the rules labelled, and
// which rules can be added — and each of those three can also be run on its own.
// What has no category after that, Claude can look at thoroughly: a stronger
// model with more context. The settings (on or off, what goes to Claude) expand
// here, not at the bottom of the page.

import { Fragment, useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { fmtDayMonthYear, fmtEuro } from "@/lib/format";
import { Button, Checkbox } from "@/components/ds";
import {
  aiRule,
  checkRule,
  ruleRule,
  useRounds,
  Progress,
  type AiItem,
  type CheckItem,
  type RuleItem,
} from "@/components/money/labelling/rounds";
import { intlLocale, tr, trx } from "@/lib/i18n";

export type AiStatus = {
  available: boolean;
  on: boolean;
  to_ask: number;
  by_ai: number;
  to_check: number;
  to_check_groups: number;
  rule_candidates: number;
  /** Still without a category, and Claude did not know earlier — with an older instruction. */
  again: number;
  /** Counterparties without a category that have not been looked at thoroughly yet. */
  thorough: number;
  model: string;
};

type AiReport = { asked: number; labelled: number; doubt: number; items: AiItem[]; rest: number; error: string | null };
type CheckReport = { checked: number; rest: number; deviating: number; items: CheckItem[]; error: string | null };
type RuleReport = { suggested: number; viewed: number; items: RuleItem[]; rest: number };

function useClaudeOn(onDone: () => void) {
  return useMutation({
    mutationFn: async (on: boolean) => {
      await api.put("/api/preferences/ai_labelling", { value: { on } });
      // On: what Claude already knew for sure applies again at once. Off: its labels come off.
      await api.post("/api/categories/relabel?everything=true");
    },
    onSuccess: onDone,
  });
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-ink-muted">{label}</dt>
      <dd className="num truncate text-lg font-medium sm:text-xl">{value}</dd>
    </div>
  );
}

const STEPS = [
  { title: tr("Claude is looking at what has no category yet…"), unit: "transactions" },
  { title: tr("Claude is checking what the rules labelled…"), unit: "counterparties" },
  { title: tr("Claude is coming up with rules…"), unit: "counterparties" },
  { title: tr("Claude is looking thoroughly at what has no category yet…"), unit: "counterparties" },
] as const;

const readAi = (v: AiReport) => ({
  count: v.asked,
  done: v.rest === 0,
  items: v.items,
  error: v.error,
  tally: { labelled: v.labelled, doubt: v.doubt },
});

type Plan = { step: number; end: number; full: boolean };

export function LabelStatus({
  coverage,
  waiting,
  most_recent,
  ai,
  onDone,
  onShow,
}: {
  coverage: number;
  waiting: number;
  most_recent: string | null;
  ai?: AiStatus;
  onDone: () => void;
  /** Jump to that kind in the queue. */
  onShow?: (kind: "doubt" | "disagree" | "rule") => void;
}) {
  const open = useRounds<AiReport, AiItem>("/api/categories/ai/analyse", readAi, onDone);
  const check = useRounds<CheckReport, CheckItem>(
    "/api/categories/ai/verify",
    (v) => ({ count: v.checked, done: v.rest === 0, items: v.items, error: v.error, tally: { deviating: v.deviating } }),
    onDone,
  );
  const rules = useRounds<RuleReport, RuleItem>(
    "/api/categories/ai/rule-suggestions",
    (v) => ({ count: v.viewed, done: v.rest === 0, items: v.items, tally: { suggested: v.suggested } }),
    onDone,
  );
  const thorough = useRounds<AiReport, AiItem>("/api/categories/ai/thorough", readAi, onDone);
  const put = useClaudeOn(onDone);
  const [settings, setSettings] = useState(false);

  const rounds = [open, check, rules, thorough] as const;
  const totals = [ai?.to_ask ?? 0, ai?.to_check_groups ?? 0, ai?.rule_candidates ?? 0, ai?.thorough ?? 0];
  // Which steps this time: the three of "check everything", or one on its own.
  const [plan, setPlan] = useState<Plan | null>(null);
  const start = (step: number, end = step, total = totals[step]) => {
    rounds.forEach((r) => r.close());
    setPlan({ step, end, full: step === 0 && end === 2 });
    rounds[step].start(total);
  };
  const everything = () => start(0, 2);
  // Put what Claude did not know with an older instruction to it again, and have it reviewed right away.
  const again = useMutation({
    mutationFn: () => api.post<{ released: number; to_ask: number }>("/api/categories/ai/retry"),
    onSuccess: (v) => start(0, 0, v.to_ask),
  });
  const current_item = plan ? rounds[plan.step] : null;

  // A step that finishes by itself starts the next. Stopped or an error: the rest waits.
  useEffect(() => {
    if (!plan || !current_item || current_item.busy || !current_item.finished || plan.step >= plan.end) return;
    const following = plan.step + 1;
    setPlan({ ...plan, step: following });
    rounds[following].start(totals[following]);
  }, [plan?.step, current_item?.busy, current_item?.finished]); // eslint-disable-line react-hooks/exhaustive-deps

  // If Claude is on and there is something new, it looks by itself — once per visit.
  const started = useRef(false);
  const next = !!ai && ai.on && (ai.to_ask > 0 || ai.to_check > 0 || ai.rule_candidates > 0);
  useEffect(() => {
    if (ai?.available && next && !started.current) {
      started.current = true;
      everything();
    }
  }, [ai?.available, next]); // eslint-disable-line react-hooks/exhaustive-deps

  const busy = rounds.some((r) => r.busy) || again.isPending;
  const error = rounds.find((r) => r.error)?.error ?? (again.error as ApiError | null)?.message ?? null;
  const done = !!plan && !busy && !!current_item?.finished && plan.step >= plan.end;
  const labelled = (open.tally.labelled ?? 0) + (thorough.tally.labelled ?? 0);
  const doubt = (open.tally.doubt ?? 0) + (thorough.tally.doubt ?? 0);
  const choices = (
    [
      { kind: "doubt", n: doubt, label: "twijfelgevallen" },
      { kind: "disagree", n: check.tally.deviating ?? 0, label: "deviations" },
      { kind: "rule", n: rules.tally.suggested ?? 0, label: "rule_suggestions" },
    ] as const
  ).filter((k) => k.n > 0);
  const delivered = labelled + choices.reduce((s, k) => s + k.n, 0);
  // Rough: Haiku a little over a cent per request of ~40, Sonnet a few cents per request of 15.
  const costs = ai ? Math.max(0.01, (ai.to_ask + ai.to_check_groups) * 0.00025 + ai.rule_candidates * 0.0003) : 0;
  const costsThorough = ai ? Math.max(0.01, ai.thorough * 0.003) : 0;

  // "Not seen yet" is something else than "no category yet". What Claude already
  // saw and did not know: again (with a better instruction) or thoroughly
  // (stronger model).
  const first = !ai
    ? null
    : ai.to_ask > 0
      ? { key: "open", label: tr("only what Claude hasn't seen yet"), n: ai.to_ask, run: () => start(0) }
      : ai.again > 0
        ? { key: "again", label: tr("have what has no category yet looked at again"), n: ai.again, run: () => again.mutate() }
        : ai.thorough > 0
          ? {
              key: "thorough",
              label: tr("have what has no category yet looked at thoroughly"),
              n: ai.thorough,
              run: () => start(3),
              explanation: tr("Claude Sonnet, with more descriptions and how you label · about {0}", fmtEuro(costsThorough)),
            }
          : { key: "open", label: tr("only what Claude hasn't seen yet"), n: 0, run: () => start(0) };
  const loose = first
    ? [
        first,
        { key: "check", label: tr("only check"), n: ai!.to_check_groups, run: () => start(1) },
        { key: "rules", label: tr("only suggest rules"), n: ai!.rule_candidates, run: () => start(2) },
      ]
    : [];

  return (
    <section
      className="flex flex-col gap-4 rounded-lg p-4 sm:p-5"
      style={{ background: "var(--surface-card)", border: "1px solid var(--rule)" }}
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <dl className="grid grid-cols-3 gap-x-6 gap-y-2 sm:gap-x-10">
          <Metric label={tr("Labelled")} value={`${coverage.toLocaleString(intlLocale, { maximumFractionDigits: 1 })}%`} />
          <Metric label={tr("Waiting for you")} value={String(waiting)} />
          <Metric
            label={tr("Last checked")}
            value={ai?.on ? (most_recent ? fmtDayMonthYear(most_recent.slice(0, 10)) : tr("never yet")) : "–"}
          />
        </dl>
        {ai?.available && (
          <div className="flex flex-wrap items-center gap-2">
            {ai.on ? (
              busy ? (
                <Button size="sm" variant="ghost" onClick={() => current_item?.stop()}>
                  {tr("Stop")}
                </Button>
              ) : (
                <Button size="sm" variant="secondary" onClick={everything}>
                  {tr("Let Claude check everything")}
                </Button>
              )
            ) : (
              <Button size="sm" variant="secondary" disabled={put.isPending} onClick={() => setSettings(true)}>
                {tr("Let Claude help")}
              </Button>
            )}
            <Button size="sm" variant="ghost" aria-expanded={settings} onClick={() => setSettings((o) => !o)}>
              {trx("Settings {0}", settings ? "▴" : "▾")}
            </Button>
          </div>
        )}
      </div>

      {ai?.available && ai.on && !busy && (
        <div className="flex flex-col gap-1 text-xs text-ink-muted">
          <p className="flex flex-wrap items-center gap-x-1">
            <span>{tr("Or")}</span>
            {loose.map((l, n) => (
              <span key={l.key} className="flex items-center gap-1">
                <button type="button" onClick={l.run} className="underline underline-offset-4 hover:text-[color:var(--ink)]">
                  {l.label}
                </button>
                <span className="num">({l.n})</span>
                {n < loose.length - 1 && <span aria-hidden>·</span>}
              </span>
            ))}
            {next && <span className="num">{trx("· about {0} in total", fmtEuro(costs))}</span>}
          </p>
          {first && "explanation" in first && <p>{first.explanation}</p>}
        </div>
      )}

      {ai?.available && !ai.on && (
        <p className="text-xs text-ink-muted">
          {tr(
            "Off. Claude, the AI of Anthropic, can suggest categories for what the rules don't recognise, check what they did label and come up with new rules. That sends the name, description, amount and date of those transactions to Anthropic (without IBANs, account and card numbers). Only if you turn it on yourself.",
          )}
        </p>
      )}

      {settings && ai && (
        <div className="flex flex-col gap-2 rounded-md p-3 text-xs" style={{ background: "var(--surface-inset)" }}>
          <label className="flex items-start gap-2 text-[12.5px]">
            <Checkbox checked={ai.on} disabled={put.isPending} aria-label={tr("Let Claude help")} onChange={(on) => put.mutate(on)} />
            <span>
              {trx(
                "Let Claude make suggestions{0}",
                <span className="block text-xs text-ink-muted">
                  {trx(
                    "What the rules and your own labels don't recognise goes to {0} at Anthropic: name, description, amount and date, without IBANs, account and card numbers. When looking thoroughly, more descriptions per counterparty go along, and the names of counterparties you often label (not of friends). If Claude is at least 80% sure, it labels it, marked as AI; otherwise it goes into the queue. Turning it off removes its labels again.",
                    ai.model,
                  )}
                </span>,
              )}
            </span>
          </label>
        </div>
      )}
      {put.isError && (
        <p className="text-xs" style={{ color: "var(--text-loss)" }}>
          {(put.error as ApiError).message}
        </p>
      )}

      {plan &&
        (busy || error) &&
        (() => {
          const step = plan.full ? tr("Step {0} of 3", plan.step + 1) : undefined;
          if (plan.step === 0) return <Progress r={open} step={step} {...STEPS[0]} rule={aiRule} summary={null} />;
          if (plan.step === 1) return <Progress r={check} step={step} {...STEPS[1]} rule={checkRule} summary={null} />;
          if (plan.step === 2) return <Progress r={rules} step={step} {...STEPS[2]} rule={ruleRule} summary={null} />;
          return <Progress r={thorough} {...STEPS[3]} rule={aiRule} summary={null} />;
        })()}
      {!plan && error && (
        <p className="text-xs" style={{ color: "var(--text-loss)" }}>
          {error}
        </p>
      )}
      {done && (
        <div className="flex items-start justify-between gap-3 rounded-md px-3 py-2 text-xs" style={{ background: "var(--surface-inset)" }}>
          <span>
            {delivered === 0 ? (
              tr("Claude has looked at everything. Nothing new.")
            ) : (
              <>
                {trx(
                  "Done: {0} labelled.{1}",
                  <b className="num">{labelled}</b>,
                  choices.length > 0 && (
                    <>
                      {" "}
                      {trx(
                        "Up to you: {0}.{1}",
                        choices.map((k, i) => (
                          <Fragment key={k.kind}>
                            {i > 0 && (i === choices.length - 1 ? tr(" and ") : ", ")}
                            <button type="button" onClick={() => onShow?.(k.kind)} className="num font-medium underline underline-offset-4">
                              {k.n} {k.label}
                            </button>
                          </Fragment>
                        )),
                        doubt > 0 && (
                          <span className="block pt-1 text-ink-muted">
                            {tr("When in doubt Claude was less than 80% sure. If most of it is right, tick “Choose all” and choose Agree.")}
                          </span>
                        ),
                      )}
                    </>
                  ),
                )}
              </>
            )}
          </span>
          <button
            type="button"
            onClick={() => {
              setPlan(null);
              rounds.forEach((r) => r.close());
            }}
            className="shrink-0 text-ink-muted underline underline-offset-4"
          >
            {tr("Close")}
          </button>
        </div>
      )}
    </section>
  );
}
