"use client";

// The queue of To label: everything that needs a decision from you, in one row
// and in one shape — who and how much at the top, below it what is there now,
// what is suggested and why, and then the buttons. The same choices everywhere:
// agree, reject or something else.
//
// Working fast: what you choose disappears at once and is only saved after a few
// seconds, so "Undo" is possible. Tick for several at once, keyboard shortcuts,
// and "Quick run" for one at a time.

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "@/lib/api";
import { fmtDayMonthYear, fmtEuro } from "@/lib/format";
import { trueMinus } from "@trackerai/ui/lib/typography";
import { Button, Checkbox, EmptyState } from "@/components/ds";
import { CategoryOptions } from "@/components/money/TransactionActions";
import SingleTransactions from "@/components/money/labelling/SingleTransactions";
import { showAmount, type Category } from "@/lib/money";
import { tr, trx } from "@/lib/i18n";

export type Kind = "own" | "doubt" | "disagree" | "unknown" | "rule" | "ai";

export type WaitItem = {
  key: string;
  kind: Kind;
  title: string;
  ids: number[];
  count: number;
  total: number;
  last: string | null;
  description: string;
  /** The description without bank noise (IBAN, references, dates). */
  remark: string;
  now: string | null;
  suggestion: string | null;
  confidence: number | null;
  reason: string | null;
  rule_possible: boolean;
  rule_id?: number;
  processor?: boolean;
};

export type QueueData = {
  items: WaitItem[];
  tellers: Record<Kind, number>;
  waiting: number;
  coverage: number;
  unknown: number;
  most_recent_checked: string | null;
  claude: boolean;
};

type Choice = "agreed" | "reject" | "otherwise";
type Decision = { kind: Kind; choice: Choice; ids: number[]; category?: string | null; rule?: boolean; rule_id?: number };

const KIND: Record<Kind, { label: string; reject: string; colour: string }> = {
  own: { label: tr("Own account?"), reject: tr("It's right"), colour: "var(--cat-5)" },
  doubt: { label: tr("Claude is unsure"), reject: tr("It's wrong"), colour: "var(--cat-3)" },
  disagree: { label: tr("Claude disagrees"), reject: tr("Original is right"), colour: "var(--cat-4)" },
  unknown: { label: tr("No category yet"), reject: "Later", colour: "var(--ink-faint)" },
  rule: { label: tr("Rule suggestion"), reject: tr("Reject"), colour: "var(--cat-2)" },
  ai: { label: tr("Labelled by Claude"), reject: tr("It's wrong"), colour: "var(--cat-1)" },
};
const ORDER: Kind[] = ["own", "doubt", "disagree", "unknown", "rule", "ai"];
const WAIT_TIME_MS = 5000;

const ruleDefault = (i: WaitItem) =>
  i.rule_possible && i.count >= 2 && (i.kind === "unknown" || i.kind === "doubt" || i.kind === "disagree");

/** What is still waiting for you: everything except what Claude already labelled, minus what you just chose. */
export function waiting(data: QueueData, away: Set<string>) {
  return data.items.filter((i) => i.kind !== "ai" && !away.has(i.key)).length;
}

/**
 * Collect decisions and send them in one go after a few seconds. Until then it can
 * be undone; what you choose disappears from view at once. Created on the page,
 * so the counter at the top moves along straight away too.
 */
export function useDecisions(onDone: () => void) {
  const [away, setAway] = useState<Set<string>>(new Set());
  const [last, setLast] = useState<{ text: string; keys: string[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const buffer = useRef<{ key: string; decision: Decision }[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const submit = useCallback(async () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    const now = buffer.current;
    buffer.current = [];
    setLast(null);
    if (now.length === 0) return;
    setBusy(true);
    try {
      await api.post("/api/labelling/decision", { decisions: now.map((b) => b.decision) });
      onDone();
    } catch (e) {
      setError((e as ApiError)?.message || tr("Saving didn't work."));
      setAway((o) => {
        const n = new Set(o);
        now.forEach((b) => n.delete(b.key));
        return n;
      });
    } finally {
      setBusy(false);
    }
  }, [onDone]);

  // Away from the page: send at once, lose nothing.
  const submitRef = useRef(submit);
  submitRef.current = submit;
  useEffect(() => () => { void submitRef.current(); }, []);

  const take = (pairs: { item: WaitItem; decision: Decision }[], text: string) => {
    if (pairs.length === 0) return;
    setError(null);
    const keys = pairs.map((p) => p.item.key);
    setAway((o) => new Set([...o, ...keys]));
    buffer.current.push(...pairs.map((p) => ({ key: p.item.key, decision: p.decision })));
    setLast({ text, keys });
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => { void submit(); }, WAIT_TIME_MS);
  };

  const undone = () => {
    if (!last) return;
    const back = new Set(last.keys);
    buffer.current = buffer.current.filter((b) => !back.has(b.key));
    setAway((o) => {
      const n = new Set(o);
      back.forEach((s) => n.delete(s));
      return n;
    });
    setLast(null);
  };

  return { away, last, busy, error, take, undone, submit };
}

export type Decisions = ReturnType<typeof useDecisions>;

export default function Queue({ data, categories, decisions: b, onDone, filter, onFilter: setFilter }: {
  data: QueueData; categories: Category[]; decisions: Decisions; onDone: () => void;
  /** Kept on the page, so Claude's summary can jump here. */
  filter: Kind | "everything"; onFilter: (f: Kind | "everything") => void;
}) {
  const [stand, setStand] = useState<"items" | "quick">("items");
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [rules, setRules] = useState<Record<string, boolean>>({});
  const [open, setOpen] = useState<string | null>(null);
  const [focus, setFocus] = useState(0);
  // Only when you choose a row yourself (tap, click or j/k) does it expand; not the first one by itself.
  const [touched, setTouched] = useState(false);
  const rows = useRef<Record<string, HTMLDivElement | null>>({});

  const visible = data.items.filter((i) =>
    !b.away.has(i.key) && (filter === "everything" ? i.kind !== "ai" : i.kind === filter));
  const spot = Math.min(focus, Math.max(visible.length - 1, 0));
  const current = visible[spot];
  const selection = visible.filter((i) => chosen.has(i.key));
  const ruleFor = (i: WaitItem) => rules[i.key] ?? ruleDefault(i);
  const telling = (s: Kind) => data.items.filter((i) => i.kind === s && !b.away.has(i.key)).length;

  const decisionFor = (i: WaitItem, choice: Choice, category?: string): Decision | null => {
    if (choice === "agreed" && !i.suggestion) return null;
    const cat = choice === "agreed" ? i.suggestion : choice === "otherwise" ? category : i.kind === "own" ? i.now : null;
    return { kind: i.kind, choice, ids: i.ids, category: cat ?? null, rule: ruleFor(i), rule_id: i.rule_id };
  };
  const choose = (items: WaitItem[], choice: Choice, category?: string) => {
    const pairs = items.flatMap((item) => {
      const decision = decisionFor(item, choice, category);
      return decision ? [{ item, decision }] : [];
    });
    const word = choice === "agreed" ? "agreed" : choice === "reject" ? "rejected" : `→ ${category}`;
    b.take(pairs, pairs.length === 1 ? `${pairs[0].item.title}: ${word}` : tr("{0} decisions: {1}", pairs.length, word));
    setChosen((o) => {
      const n = new Set(o);
      pairs.forEach((p) => n.delete(p.item.key));
      return n;
    });
  };

  // Keyboard shortcuts: j/k to browse, a agree, x reject, space to tick, u undo.
  useEffect(() => {
    const test = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (e.metaKey || e.ctrlKey || e.altKey || (target && /^(INPUT|SELECT|TEXTAREA)$/.test(target.tagName))) return;
      if (e.key === "j" || e.key === "ArrowDown") {
        setFocus((f) => (touched ? Math.min(f + 1, visible.length - 1) : f));
        setTouched(true);
        e.preventDefault();
      } else if (e.key === "k" || e.key === "ArrowUp") { setFocus((f) => Math.max(f - 1, 0)); setTouched(true); e.preventDefault(); }
      else if (e.key === "a" && current) choose([current], "agreed");
      else if (e.key === "x" && current) choose([current], "reject");
      else if (e.key === "u") b.undone();
      else if (e.key === " " && current && stand === "items") {
        setChosen((o) => {
          const n = new Set(o);
          n.has(current.key) ? n.delete(current.key) : n.add(current.key);
          return n;
        });
        e.preventDefault();
      }
    };
    window.addEventListener("keydown", test);
    return () => window.removeEventListener("keydown", test);
  });
  useEffect(() => {
    if (stand === "items" && current) rows.current[current.key]?.scrollIntoView({ block: "nearest" });
  }, [focus, stand]); // eslint-disable-line react-hooks/exhaustive-deps

  const chooseFilter = (f: Kind | "everything") => { setFilter(f); setFocus(0); setChosen(new Set()); };
  const kinds = ORDER.filter((s) => telling(s) > 0);

  return (
    <section id="queue" className="flex min-w-0 scroll-mt-20 flex-col gap-3">
      {/* Soorten: één rij, op een telefoon zijwaarts te scrollen. */}
      <div className="-mx-1 overflow-x-auto no-scrollbar">
        <div className="flex w-max gap-1.5 px-1" role="tablist" aria-label={tr("Kind")}>
          <Chip active={filter === "everything"} onClick={() => chooseFilter("everything")}>{trx("All {0}", <span className="num opacity-70">{waiting(data, b.away)}</span>)}</Chip>
          {kinds.map((s) => (
            <Chip key={s} active={filter === s} onClick={() => chooseFilter(s)}>
              <span aria-hidden className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: KIND[s].colour }} />
              {KIND[s].label} <span className="num opacity-70">{telling(s)}</span>
            </Chip>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-ink-muted">
        {stand === "items" && visible.length > 0 ? (
          <label className="flex items-center gap-2">
            <Checkbox checked={selection.length > 0 && selection.length === visible.length} aria-label={tr("Choose all")}
              onChange={(on) => setChosen(on ? new Set(visible.map((i) => i.key)) : new Set())} />
            <span>{selection.length > 0 ? tr("{0} chosen", selection.length) : tr("Choose all")}</span>
          </label>
        ) : <span />}
        <span className="hidden lg:inline">{tr("j/k browse · a agree · x reject · space choose · u undo")}</span>
        <div className="flex rounded-full p-0.5" style={{ background: "var(--surface-inset)" }} role="tablist" aria-label={tr("View")}>
          {(["items", "quick"] as const).map((s) => (
            <button key={s} type="button" role="tab" aria-selected={stand === s}
              onClick={() => { setStand(s); setFocus(0); }}
              className="rounded-full px-3 py-1 transition-colors"
              style={stand === s ? { background: "var(--surface-card)", color: "var(--ink)", boxShadow: "0 1px 2px rgb(0 0 0 / 0.08)" } : undefined}>
              {s === "items" ? tr("List") : tr("Go through quickly")}
            </button>
          ))}
        </div>
      </div>

      {selection.length > 0 && stand === "items" && (
        <div className="sticky top-[60px] z-10 flex flex-wrap items-center gap-2 rounded-md px-3 py-2 text-xs"
          style={{ background: "var(--surface-card)", border: "1px solid var(--rule)", boxShadow: "0 2px 8px rgb(0 0 0 / 0.08)" }}>
          <b className="num">{trx("{0} chosen", selection.length)}</b>
          {selection.some((i) => i.suggestion) && (
            <Button size="sm" variant="secondary" onClick={() => choose(selection, "agreed")}>{trx("✓ Agree {0}", <span className="num">({selection.filter((i) => i.suggestion).length})</span>)}</Button>
          )}
          <Button size="sm" variant="ghost" onClick={() => choose(selection, "reject")}>{tr("Reject")}</Button>
          <span className="w-40">
            <CategoryChoice categories={categories} label={tr("Other category…")}
              onChoose={(c) => choose(selection.filter((i) => i.kind !== "rule"), "otherwise", c)} />
          </span>
          <button type="button" onClick={() => setChosen(new Set())} className="ml-auto text-ink-muted underline underline-offset-4">{tr("Clear selection")}</button>
        </div>
      )}

      {visible.length === 0 ? (
        <EmptyState
          title={filter === "everything" ? tr("Nothing left to label") : tr("Nothing left in this list")}
          body={filter === "everything"
            ? tr("Everything has a category and nothing looks wrong. New transactions the rules don't recognise come here by themselves.")
            : tr("Choose another kind above, or All.")}
        />
      ) : stand === "quick" && current ? (
        <QuickCard item={current} position={spot + 1} start={visible.length} categories={categories}
          rule={ruleFor(current)} onRule={(on) => setRules((o) => ({ ...o, [current.key]: on }))}
          onChoose={(choice, cat) => choose([current], choice, cat)}
          onNext={() => setFocus((f) => Math.min(f + 1, visible.length - 1))}
          onPrevious={() => setFocus((f) => Math.max(f - 1, 0))} />
      ) : (
        <div className="overflow-hidden rounded-lg" style={{ border: "1px solid var(--rule)", background: "var(--surface-card)" }}>
          {visible.map((i, n) => (
            <div key={i.key} ref={(el) => { rows.current[i.key] = el; }}
              onClick={() => { setFocus(n); setTouched(true); }}
              style={{ borderTop: n === 0 ? undefined : "1px solid var(--rule)",
                boxShadow: n === spot ? "inset 3px 0 0 var(--brand)" : undefined }}>
              <Row item={i} showKind={filter === "everything"} chosen={chosen.has(i.key)} categories={categories}
                onChosen={(on) => setChosen((o) => {
                  const s = new Set(o);
                  on ? s.add(i.key) : s.delete(i.key);
                  return s;
                })}
                rule={ruleFor(i)} onRule={(on) => setRules((o) => ({ ...o, [i.key]: on }))}
                open={open === i.key} onOpen={() => setOpen((o) => (o === i.key ? null : i.key))}
                onChoose={(choice, cat) => choose([i], choice, cat)} onDone={onDone}
                expanded={touched && n === spot} />
            </div>
          ))}
        </div>
      )}

      {b.error && <p className="text-xs" style={{ color: "var(--text-loss)" }}>{b.error}</p>}
      {(b.last || b.busy) && (
        <div className="fixed bottom-4 left-1/2 z-30 flex max-w-[calc(100vw-2rem)] -translate-x-1/2 items-center gap-3 rounded-full px-4 py-2 text-xs"
          style={{ background: "var(--ink)", color: "var(--surface-card)" }} role="status" aria-live="polite">
          {b.last ? (
            <>
              <span className="truncate">{b.last.text}</span>
              <button type="button" onClick={b.undone} className="shrink-0 font-medium underline underline-offset-4">{tr("Undo")}</button>
            </>
          ) : <span>{tr("Saving…")}</span>}
        </div>
      )}
    </section>
  );
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" role="tab" aria-selected={active} onClick={onClick}
      className="flex items-center gap-1.5 whitespace-nowrap rounded-full px-3 py-1 text-xs transition-colors"
      style={active
        ? { background: "var(--ink)", color: "var(--surface-card)" }
        : { border: "1px solid var(--rule)", background: "var(--surface-card)" }}>
      {children}
    </button>
  );
}

/** A compact select list for a category; choosing is a decision at once. */
function CategoryChoice({ categories, label, onChoose }: {
  categories: Category[]; label: string; onChoose: (category: string) => void;
}) {
  return (
    <select aria-label={label} value="" onChange={(e) => e.target.value && onChoose(e.target.value)}
      className="ds-select h-8 !w-full !min-w-0 py-0 text-xs">
      <option value="">{label}</option>
      <CategoryOptions categories={categories} />
    </select>
  );
}

function Amount({ item, large = false }: { item: WaitItem; large?: boolean }) {
  if (item.kind === "rule") return null;
  const amount = showAmount(item.total);
  return (
    <span className={`num shrink-0 ${large ? "text-lg" : "text-[13.5px]"}`} style={amount > 0 ? { color: "var(--text-gain)" } : undefined}>
      {trueMinus(fmtEuro(amount))}
    </span>
  );
}

function Caption({ item, showKind }: { item: WaitItem; showKind: boolean }) {
  const share_out = item.kind === "rule"
    ? [tr("rule · affects {0}", item.count)]
    : [`${item.count}×`, item.last ? tr("last {0}", fmtDayMonthYear(item.last)) : null];
  return (
    <span className="flex flex-wrap items-center gap-x-1.5 text-xs text-ink-muted">
      <span className="num">{share_out.filter(Boolean).join(" · ")}</span>
      {showKind && (
        <>
          <span aria-hidden>·</span>
          <span className="flex items-center gap-1">
            <span aria-hidden className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: KIND[item.kind].colour }} />
            {KIND[item.kind].label}
          </span>
        </>
      )}
    </span>
  );
}

function Suggestion({ item }: { item: WaitItem }) {
  return (
    <p className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[12.5px]">
      {item.now && item.now !== item.suggestion && (
        <>
          <span className="text-ink-muted">{item.now}</span>
          <span aria-hidden className="text-ink-muted">→</span>
        </>
      )}
      {item.suggestion
        ? <span className="font-medium">{item.suggestion}</span>
        : <span className="text-ink-muted">{tr("no category yet")}</span>}
      {item.confidence != null && item.confidence > 0 && (
        <span className="num rounded px-1.5 text-[11px] text-ink-muted" style={{ background: "var(--surface-inset)" }}>
          {Math.round(item.confidence * 100)}%
        </span>
      )}
      {item.reason && <span className="text-ink-muted">· {item.reason}</span>}
    </p>
  );
}

function Actions({ item, categories, rule, onRule, onChoose, large = false }: {
  item: WaitItem; categories: Category[]; rule: boolean; onRule: (on: boolean) => void;
  onChoose: (choice: Choice, category?: string) => void; large?: boolean;
}) {
  const size = large ? "md" : "sm";
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {item.suggestion && (
        <Button size={size} variant="secondary" onClick={() => onChoose("agreed")}>
          {item.kind === "ai" ? tr("✓ Correct") : item.kind === "rule" ? tr("✓ Accept rule") : `✓ ${item.suggestion}`}
        </Button>
      )}
      <Button size={size} variant="ghost" onClick={() => onChoose("reject")}>{KIND[item.kind].reject}</Button>
      {item.kind !== "rule" && (
        <span className="w-40">
          <CategoryChoice categories={categories} label={item.suggestion ? tr("Other…") : tr("Choose category…")}
            onChoose={(c) => onChoose("otherwise", c)} />
        </span>
      )}
      {item.rule_possible && item.kind !== "own" && item.kind !== "rule" && (
        <label className="flex items-center gap-1.5 pl-1 text-xs text-ink-muted" title={tr("Make it a rule, so the next payment goes right by itself")}>{trx("{0}as a rule from now on", <Checkbox checked={rule} onChange={onRule} aria-label={tr("As a rule from now on")} />)}</label>
      )}
    </div>
  );
}

/**
 * The description, clean and always in full: long text runs on to the next line.
 * The raw bank row (with IBAN and references) is one click behind it — or shown
 * by itself when you tap the row or go to it with j/k.
 */
function Description({ item, open }: { item: WaitItem; open: boolean }) {
  const [raw, setRaw] = useState(false);
  const clean = item.remark || item.description;
  if (!clean) return null;
  const hasRaw = !!item.description && item.description !== clean;
  const showRaw = hasRaw && (raw || open);
  return (
    <div className="flex flex-col gap-1 text-xs text-ink-muted">
      <p className="whitespace-normal break-words">
        {clean}
        {hasRaw && (
          <>
            {" "}
            <button type="button" onClick={(e) => { e.stopPropagation(); setRaw((o) => !o); }}
              className="whitespace-nowrap underline underline-offset-4 hover:text-[color:var(--ink)]">
              {showRaw ? tr("less") : tr("whole bank description")}
            </button>
          </>
        )}
      </p>
      {showRaw && (
        <p className="whitespace-pre-line break-words rounded px-2 py-1" style={{ background: "var(--surface-inset)" }}>
          {item.description}
        </p>
      )}
    </div>
  );
}

function Row({ item, showKind, chosen, onChosen, categories, rule, onRule, open, onOpen, onChoose, onDone, expanded }: {
  item: WaitItem; showKind: boolean; chosen: boolean; onChosen: (on: boolean) => void; categories: Category[];
  rule: boolean; onRule: (on: boolean) => void; open: boolean; onOpen: () => void;
  onChoose: (choice: Choice, category?: string) => void; onDone: () => void; expanded: boolean;
}) {
  const loose = item.kind === "unknown" && item.count > 1;
  return (
    <div className="group">
      <div className="flex flex-col gap-2 px-3 py-2.5 sm:px-4 lg:flex-row lg:items-start lg:gap-4">
        <div className="flex min-w-0 flex-1 gap-3">
          <div className="pt-0.5"><Checkbox checked={chosen} aria-label={tr("Choose {0}", item.title)} onChange={onChosen} /></div>
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <span className={item.kind === "rule" ? "font-mono text-[13px]" : "text-[13.5px] font-medium"}>{item.title}</span>
              <Amount item={item} />
              <Caption item={item} showKind={showKind} />
            </div>
            <Suggestion item={item} />
            <Description item={item} open={expanded} />
            {loose && (
              <button type="button" onClick={onOpen} className="self-start text-xs text-ink-muted underline underline-offset-4">
                {open ? tr("Collapse") : item.processor ? tr("See them separately ({0}): each payment is a different shop", item.count) : tr("See them separately ({0})", item.count)}
              </button>
            )}
          </div>
        </div>
        <RowActions item={item} categories={categories} rule={rule} onRule={onRule} onChoose={onChoose} />
      </div>
      {open && loose && (
        <div className="px-3 pb-3 sm:px-4 lg:pl-11"><SingleTransactions ids={item.ids} categories={categories} onDone={onDone} /></div>
      )}
    </div>
  );
}

/**
 * The buttons of a row, on the right and in fixed columns: agree, reject,
 * otherwise sit in exactly the same place in every row, so you can choose quickly
 * one after the other without searching. No suggestion: that box stays empty.
 */
function RowActions({ item, categories, rule, onRule, onChoose }: {
  item: WaitItem; categories: Category[]; rule: boolean; onRule: (on: boolean) => void;
  onChoose: (choice: Choice, category?: string) => void;
}) {
  const agreed = item.kind === "ai" ? tr("Correct") : item.kind === "rule" ? tr("Accept rule") : item.suggestion;
  return (
    <div className="flex shrink-0 flex-col items-start gap-1 pl-7 lg:items-end lg:pl-0">
      <div className="grid grid-cols-[10rem_7rem_8.5rem] items-center gap-1.5">
        {item.suggestion ? (
          <Button size="sm" variant="secondary" block title={tr("Agree: {0} (a)", item.suggestion)} onClick={() => onChoose("agreed")}>
            <span className="truncate">✓ {agreed}</span>
          </Button>
        ) : <span aria-hidden />}
        <Button size="sm" variant="ghost" block title={`${KIND[item.kind].reject} (x)`} onClick={() => onChoose("reject")}>
          {KIND[item.kind].reject}
        </Button>
        {item.kind !== "rule"
          ? <CategoryChoice categories={categories} label={item.suggestion ? tr("Other…") : tr("Choose category…")} onChoose={(c) => onChoose("otherwise", c)} />
          : <span aria-hidden />}
      </div>
      {item.rule_possible && item.kind !== "own" && item.kind !== "rule" && (
        <label className="flex items-center gap-1.5 text-xs text-ink-muted" title={tr("Make it a rule, so the next payment goes right by itself")}>{trx("{0}as a rule from now on", <Checkbox checked={rule} onChange={onRule} aria-label={tr("As a rule from now on")} />)}</label>
      )}
    </div>
  );
}

/** One at a time, large: choose and move on. For a quick round, also on your phone. */
function QuickCard({ item, position, start, categories, rule, onRule, onChoose, onNext, onPrevious }: {
  item: WaitItem; position: number; start: number; categories: Category[]; rule: boolean;
  onRule: (on: boolean) => void; onChoose: (choice: Choice, category?: string) => void;
  onNext: () => void; onPrevious: () => void;
}) {
  return (
    <div className="flex flex-col gap-4 rounded-lg p-4 sm:p-6" style={{ border: "1px solid var(--rule)", background: "var(--surface-card)" }}>
      <div className="flex items-center justify-between text-xs text-ink-muted">
        <span className="num">{trx("{0} of {1}", position, start)}</span>
        <span className="flex items-center gap-1">
          <span aria-hidden className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: KIND[item.kind].colour }} />
          {KIND[item.kind].label}
        </span>
      </div>
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className={item.kind === "rule" ? "font-mono text-lg" : "text-lg font-medium"}>{item.title}</span>
          <Caption item={item} showKind={false} />
        </div>
        <Amount item={item} large />
      </div>
      {item.remark && <p className="text-[13px] text-ink-muted">{item.remark}</p>}
      {item.description && item.description !== item.remark && (
        <p className="break-words text-xs text-ink-muted">{item.description}</p>
      )}
      <div className="rounded-md px-3 py-2.5" style={{ background: "var(--surface-inset)" }}>
        <Suggestion item={item} />
      </div>
      <Actions item={item} categories={categories} rule={rule} onRule={onRule} onChoose={onChoose} large />
      <div className="flex items-center justify-between border-t pt-3 text-xs text-ink-muted" style={{ borderColor: "var(--rule)" }}>
        <button type="button" onClick={onPrevious} className="underline underline-offset-4">{tr("← Previous")}</button>
        <span className="hidden sm:inline">{tr("a agree · x reject · u undo")}</span>
        <button type="button" onClick={onNext} className="underline underline-offset-4">{tr("Skip →")}</button>
      </div>
    </div>
  );
}
