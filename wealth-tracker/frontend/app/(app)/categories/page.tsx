"use client";

// Categories — the taxonomy and the rules that fill it.
//
// The rules are deliberately open and editable here instead of hidden in code. A
// labelling engine you cannot inspect is an engine you have to take at its word,
// and that is exactly wrong with money: you want to be able to see *why*
// something fell under Supermarkt, and adjust it when it is not right.
//
// Three things that decide the order and that the screen therefore shows:
//
//   * **Lower priority wins, and the first match stops the search.** The order
//     *is* the logic. INTERNAL is at 10 so a savings transfer is never hijacked
//     by a spending rule.
//   * **The field decides where to look.** For a card payment the shop is in the
//     name; for a payment processor it is in the description.
//   * **The type makes a total readable.** EXPENSE, INCOME or INTERNAL. Without
//     that distinction money you get back from a housemate counts as spending,
//     with a minus sign.

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import FixedCostsAdmin from "@/components/money/FixedCostsAdmin";
import { Button, Input, Section, Select } from "@/components/ds";
import {
  DIRECTIONS,
  FIELDS,
  type Category,
  type CategoryType,
  type RelabelReport,
  type Rule,
  type Direction,
  type Field,
} from "@/lib/money";
import { tr, trx } from "@/lib/i18n";
import { COLUMN_OF, COLUMN_ORDER, CountsAsHelp, TypeChoice } from "@/components/money/CategoryColumns";

type List = { categories: Category[]; rules: Rule[] };

function NewCategory({ onDone }: { onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [group_name, setGroup] = useState("");
  const [name, setName] = useState("");
  const [type, setType] = useState<CategoryType>("EXPENSE");

  const create = useMutation({
    mutationFn: () => api.post("/api/categories", { group_name, name, type }),
    onSuccess: () => {
      setOpen(false);
      setName("");
      onDone();
    },
  });

  if (!open) {
    return (
      <Button variant="secondary" onClick={() => setOpen(true)}>
        {tr("Add category")}
      </Button>
    );
  }

  return (
    <form
      className="flex flex-wrap items-end gap-2 py-2"
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate();
      }}
    >
      <Input label={tr("Group")} placeholder={tr("Housing")} value={group_name} onChange={(e) => setGroup(e.target.value)} required />
      <Input
        label={tr("Name")}
        placeholder={tr("Babysitter")}
        value={name}
        onChange={(e) => setName(e.target.value)}
        required
        error={create.isError ? (create.error as ApiError).message : undefined}
      />
      <Select label={tr("Counts as")} value={type} onChange={(e) => setType(e.target.value as CategoryType)}>
        {COLUMN_ORDER.map((t) => (
          <option key={t} value={t}>
            {COLUMN_OF[t]()}
          </option>
        ))}
      </Select>
      <Button type="submit" variant="primary" disabled={create.isPending}>
        {tr("Add")}
      </Button>
      <Button variant="ghost" onClick={() => setOpen(false)}>
        {tr("Cancel")}
      </Button>
    </form>
  );
}

function NewRule({ categories, onDone }: { categories: Category[]; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [priority, setPriority] = useState("25");
  const [field, setField] = useState<Field>("N");
  const [pattern, setPattern] = useState("");
  const [direction, setDirection] = useState<Direction>("");
  const [category, setCategory] = useState(categories[0]?.name ?? "");

  const create = useMutation({
    mutationFn: () =>
      api.post("/api/categories/rules", {
        priority: Number(priority),
        field,
        pattern,
        direction,
        category,
      }),
    onSuccess: () => {
      setOpen(false);
      setPattern("");
      onDone();
    },
  });

  if (!open) {
    return (
      <Button variant="secondary" onClick={() => setOpen(true)}>
        {tr("Add rule")}
      </Button>
    );
  }

  return (
    <form
      className="flex flex-wrap items-end gap-2 py-2"
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate();
      }}
    >
      <Input
        label={tr("Priority")}
        type="number"
        className="w-24"
        hint={tr("lower wins")}
        value={priority}
        onChange={(e) => setPriority(e.target.value)}
        required
      />
      <Select label={tr("Look at")} value={field} onChange={(e) => setField(e.target.value as Field)}>
        {FIELDS.map((v) => (
          <option key={v.value} value={v.value}>
            {v.label}
          </option>
        ))}
      </Select>
      <Input
        label={tr("Pattern")}
        placeholder="ALBERT HEIJN|JUMBO"
        hint={tr("Regular expression, capitals")}
        value={pattern}
        onChange={(e) => setPattern(e.target.value)}
        required
        disabled={field === "P"}
        error={create.isError ? (create.error as ApiError).message : undefined}
      />
      <Select label={tr("Direction")} value={direction} onChange={(e) => setDirection(e.target.value as Direction)}>
        {DIRECTIONS.map((r) => (
          <option key={r.value} value={r.value}>
            {r.label}
          </option>
        ))}
      </Select>
      <Select label={tr("Category")} value={category} onChange={(e) => setCategory(e.target.value)}>
        {categories.map((c) => (
          <option key={c.id} value={c.name}>
            {c.name}
          </option>
        ))}
      </Select>
      <Button type="submit" variant="primary" disabled={create.isPending}>
        {tr("Add")}
      </Button>
      <Button variant="ghost" onClick={() => setOpen(false)}>
        {tr("Cancel")}
      </Button>
    </form>
  );
}

/**
 * The name of a main category, with "Rename". A name that already exists merges
 * the two; a budget goes along (and adds up).
 */
function GroupHeader({ group_name, groups, onDone }: { group_name: string; groups: string[]; onDone: () => void }) {
  const [edit, setEdit] = useState(false);
  const [name, setName] = useState(group_name);
  const rename = useMutation({
    mutationFn: () => api.put("/api/categories/groups", { old: group_name, new_name: name.trim() }),
    onSuccess: () => {
      setEdit(false);
      onDone();
    },
  });
  const together = name.trim() !== group_name && groups.includes(name.trim());
  if (!edit) {
    return (
      <div className="flex items-center gap-3 pb-1">
        <h3 className="text-xs uppercase tracking-wide text-ink-muted">{group_name}</h3>
        <button
          type="button"
          onClick={() => {
            setName(group_name);
            setEdit(true);
          }}
          className="text-xs text-ink-muted underline underline-offset-4 hover:text-[color:var(--ink)]"
        >
          {tr("Rename")}
        </button>
      </div>
    );
  }
  return (
    <form
      className="flex flex-wrap items-center gap-2 pb-1"
      onSubmit={(e) => {
        e.preventDefault();
        if (name.trim() && name.trim() !== group_name) rename.mutate();
        else setEdit(false);
      }}
    >
      <input
        autoFocus
        className="ds-input h-8 w-56 text-xs"
        value={name}
        onChange={(e) => setName(e.target.value)}
        aria-label={tr("New name for {0}", group_name)}
      />
      <Button size="sm" variant="secondary" type="submit" disabled={rename.isPending || !name.trim()}>
        {together ? tr("Merge") : tr("Save")}
      </Button>
      <Button size="sm" variant="ghost" onClick={() => setEdit(false)}>
        {tr("Cancel")}
      </Button>
      {together && <span className="text-xs text-ink-muted">{trx("Merges with {0}; budgets add up.", name.trim())}</span>}
      {rename.isError && (
        <span className="text-xs" style={{ color: "var(--text-loss)" }}>
          {(rename.error as Error).message}
        </span>
      )}
    </form>
  );
}

/**
 * The name of a category, with "Rename". Transactions, rules and suggestions go
 * along. Names the app itself relies on stay.
 */
function CategoryName({ category, onDone }: { category: Category; onDone: () => void }) {
  const [edit, setEdit] = useState(false);
  const [name, setName] = useState(category.name);
  const rename = useMutation({
    mutationFn: () => api.put(`/api/categories/${category.id}/name`, { name: name.trim() }),
    onSuccess: () => {
      setEdit(false);
      onDone();
    },
  });
  if (edit) {
    return (
      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim() && name.trim() !== category.name) rename.mutate();
          else setEdit(false);
        }}
      >
        <input
          autoFocus
          className="ds-input h-8 w-52 text-xs"
          value={name}
          onChange={(e) => setName(e.target.value)}
          aria-label={tr("New name for {0}", category.name)}
        />
        <Button size="sm" variant="secondary" type="submit" disabled={rename.isPending || !name.trim()}>
          {tr("Save")}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            setName(category.name);
            setEdit(false);
          }}
        >
          {tr("Cancel")}
        </Button>
        {rename.isError && (
          <span className="text-xs" style={{ color: "var(--text-loss)" }}>
            {(rename.error as Error).message}
          </span>
        )}
      </form>
    );
  }
  return (
    <span className="flex items-center gap-2 text-[12.5px]">
      {category.name}
      {category.is_fixed ? (
        <span className="text-xs text-ink-muted" title={tr("The app relies on this name itself, so it stays")}>
          {tr("fixed name")}
        </span>
      ) : (
        <button
          type="button"
          onClick={() => {
            setName(category.name);
            setEdit(true);
          }}
          className="text-xs text-ink-muted underline underline-offset-4 hover:text-[color:var(--ink)]"
        >
          {tr("Rename")}
        </button>
      )}
    </span>
  );
}

/** Moves a category to another main category, or to a new one. */
function MoveTo({ category, groups, onDone }: { category: Category; groups: string[]; onDone: () => void }) {
  const [next, setNew] = useState<string | null>(null);
  const move = useMutation({
    mutationFn: (group_name: string) => api.put(`/api/categories/${category.id}/group`, { group_name }),
    onSuccess: () => {
      setNew(null);
      onDone();
    },
  });
  if (next !== null) {
    return (
      <form
        className="flex items-center gap-1"
        onSubmit={(e) => {
          e.preventDefault();
          if (next.trim()) move.mutate(next.trim());
        }}
      >
        <input
          autoFocus
          className="ds-input h-8 w-44 text-xs"
          placeholder={tr("Main category name")}
          value={next}
          onChange={(e) => setNew(e.target.value)}
          aria-label={tr("New main category for {0}", category.name)}
        />
        <Button size="sm" variant="secondary" type="submit" disabled={!next.trim() || move.isPending}>
          {tr("Move")}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setNew(null)}>
          {tr("Cancel")}
        </Button>
      </form>
    );
  }
  return (
    <select
      aria-label={tr("Move {0} to", category.name)}
      value=""
      disabled={move.isPending}
      onChange={(e) => {
        const v = e.target.value;
        if (v === "__nieuw__") setNew("");
        else if (v) move.mutate(v);
      }}
      className="ds-select h-8 w-44 py-0 text-xs"
    >
      <option value="">{tr("Move to…")}</option>
      {groups
        .filter((g) => g !== category.group_name)
        .map((g) => (
          <option key={g} value={g}>
            {g}
          </option>
        ))}
      <option value="__nieuw__">{tr("New main category…")}</option>
    </select>
  );
}

export default function CategoriesPage() {
  const qc = useQueryClient();
  const [showRules, setShowRules] = useState(false);

  const items = useQuery({
    queryKey: ["categories"],
    queryFn: () => api.get<List>("/api/categories"),
  });
  // A new rule or category changes labels everywhere.
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["categories"] });
    qc.invalidateQueries({ queryKey: ["bank_transactions"] });
  };

  const labelling = useMutation({
    mutationFn: () => api.post<RelabelReport>("/api/categories/relabel?everything=true"),
    onSuccess: refresh,
  });
  const ruleAway = useMutation({
    mutationFn: (id: number) => api.del(`/api/categories/rules/${id}`),
    onSuccess: refresh,
  });
  const categoryAway = useMutation({
    mutationFn: (id: number) => api.del(`/api/categories/${id}`),
    onSuccess: refresh,
  });

  if (items.isLoading) {
    return <div className="h-72 animate-pulse rounded" style={{ background: "var(--surface-inset)" }} />;
  }
  if (items.isError) {
    return (
      <p className="py-10 text-sm" style={{ color: "var(--text-loss)" }}>
        {tr("Categories could not load. Try again.")}
      </p>
    );
  }

  const categories = items.data?.categories ?? [];
  const rules = items.data?.rules ?? [];
  const onGroup = categories.reduce<Record<string, Category[]>>((acc, c) => {
    (acc[c.group_name] ??= []).push(c);
    return acc;
  }, {});
  const rulesPerCategory = rules.reduce<Record<string, number>>((acc, r) => {
    acc[r.category] = (acc[r.category] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="flex flex-col gap-8">
      <p className="text-sm text-ink-muted">
        {trx(
          "Here you set up your categories, the rules that fill them and what counts as a fixed cost. You label transactions at {0} (a selection or one transaction) and at {1} (what has no category yet, or looks wrong).",
          <Link href="/spending/transactions" className="underline underline-offset-4">
            {tr("Transactions")}
          </Link>,
          <Link href="/spending/labelling" className="underline underline-offset-4">
            {tr("To label")}
          </Link>,
        )}
      </p>

      <Section
        label={tr("Categories")}
        meta={<span className="num">{trx("{0} in {1} groups", categories.length, Object.keys(onGroup).length)}</span>}
        info={
          <>
            {trx(
              "Next to each category is where it counts on Net worth: Saved (as spending or income) or Bank & cash, for money that isn't income or spending.{0} is money between your own accounts. That's not an expense, even though it leaves your account. Change it with the selector; the categories the app relies on keep theirs. Market and Debt on Net worth come from your holdings and debt balances, not from categories. Rename a main category with “Rename”; put a category under another (or new) main category with “Move to…”. Labels, rules and budgets move along.",
              <strong> {tr("Internal")}</strong>,
            )}
          </>
        }
        action={
          <Button size="sm" variant="ghost" disabled={labelling.isPending} onClick={() => labelling.mutate()}>
            {labelling.isPending ? tr("Working…") : tr("Relabel everything")}
          </Button>
        }
      >
        {labelling.data && (
          <p className="py-2 text-sm">
            {trx(
              "{0} transactions labelled, {1} still unknown: {2}.",
              labelling.data.labelled,
              labelling.data.unknown,
              <strong>{trx("{0}% coverage", labelling.data.coverage)}</strong>,
            )}
          </p>
        )}

        <CountsAsHelp />

        <div className="flex flex-col gap-5 py-2">
          {Object.entries(onGroup).map(([group_name, items]) => (
            <div key={group_name}>
              <GroupHeader group_name={group_name} groups={Object.keys(onGroup)} onDone={() => qc.invalidateQueries()} />
              <ul className="flex flex-col">
                {items.map((c) => (
                  <li key={c.id} className="flex items-center justify-between gap-3 py-1.5" style={{ borderTop: "1px solid var(--rule)" }}>
                    <CategoryName category={c} onDone={() => qc.invalidateQueries()} />
                    <span className="flex items-center gap-3">
                      <TypeChoice category={c} />
                      {c.name !== "Onbekend" && <MoveTo category={c} groups={Object.keys(onGroup)} onDone={() => qc.invalidateQueries()} />}
                      <span className="num text-xs text-ink-muted">{trx("{0} rules", rulesPerCategory[c.name] ?? 0)}</span>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          if (window.confirm(tr('Delete "{0}"? Rules pointing to it will then label to nothing.', c.name))) {
                            categoryAway.mutate(c.id);
                          }
                        }}
                      >
                        {tr("Delete")}
                      </Button>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="pt-2">
          <NewCategory onDone={refresh} />
        </div>
      </Section>

      <Section
        label={tr("Rules")}
        meta={<span className="num">{rules.length}</span>}
        info={
          <>
            {trx(
              "By priority, low to high. The {0} and the search stops there, so the order is the logic. Payment processors such as Mollie or CCV get a second round against the description, because that's where the real shop is.",
              <strong>{tr("first matching rule wins")}</strong>,
            )}
          </>
        }
        action={
          <Button size="sm" variant="ghost" onClick={() => setShowRules((v) => !v)}>
            {showRules ? tr("Collapse") : tr("Expand")}
          </Button>
        }
      >
        {showRules && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-[12.5px]">
              <thead>
                <tr className="text-left text-ink-muted">
                  <th className="py-1.5 font-normal">{tr("Prio")}</th>
                  <th className="py-1.5 font-normal">{tr("Looks at")}</th>
                  <th className="py-1.5 font-normal">{tr("Pattern")}</th>
                  <th className="py-1.5 font-normal">{tr("Direction")}</th>
                  <th className="py-1.5 font-normal">{tr("Category")}</th>
                  <th className="py-1.5" />
                </tr>
              </thead>
              <tbody>
                {rules.map((r) => (
                  <tr key={r.id} style={{ borderTop: "1px solid var(--rule)" }}>
                    <td className="num py-2 align-top">{r.priority}</td>
                    <td className="py-2 align-top text-ink-muted">{FIELDS.find((v) => v.value === r.field)?.label ?? r.field}</td>
                    <td className="py-2 align-top">
                      <code className="num text-[11.5px]">{r.pattern}</code>
                    </td>
                    <td className="py-2 align-top text-ink-muted">{DIRECTIONS.find((x) => x.value === r.direction)?.label}</td>
                    <td className="py-2 align-top">{r.category}</td>
                    <td className="py-2 text-right align-top">
                      <Button size="sm" variant="ghost" onClick={() => ruleAway.mutate(r.id)}>
                        {tr("Delete")}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="pt-2">
          <NewRule categories={categories} onDone={refresh} />
        </div>
      </Section>

      <FixedCostsAdmin />
    </div>
  );
}
