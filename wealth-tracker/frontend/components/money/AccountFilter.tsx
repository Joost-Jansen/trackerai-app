"use client";
import { accountGroups } from "@/lib/account-groups";
import type { Account } from "@/lib/money";
import { tr, trx } from "@/lib/i18n";

export default function AccountFilter({
  accounts,
  value,
  onChange,
}: {
  accounts: Account[];
  value: string;
  onChange: (value: string) => void;
}) {
  const groups = accountGroups(accounts);
  const selected = groups.find((g) => value === `bank:${g.id}` || g.accounts.some((a) => String(a.id) === value));
  const pill = (id: string, label: string, active: boolean) => (
    <button
      key={id}
      type="button"
      aria-pressed={active}
      onClick={() => onChange(id)}
      className="rounded-full border px-3 py-1.5 text-xs transition-colors"
      style={{
        borderColor: active ? "var(--text-primary)" : "var(--rule)",
        background: active ? "var(--surface-inset)" : "transparent",
        fontWeight: active ? 600 : 400,
      }}
    >
      {label}
    </button>
  );
  return (
    <div className="flex flex-col gap-2 pb-5" role="group" aria-label={tr("Filter accounts")}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="mr-1 text-xs text-ink-muted">{tr("Accounts")}</span>
        {pill("", tr("All"), value === "")}
        {groups.map((g) =>
          pill(
            g.accounts.length > 1 ? `bank:${g.id}` : String(g.accounts[0].id),
            `${g.name}${g.accounts.length > 1 ? ` · ${g.accounts.length}` : ""}`,
            selected?.id === g.id,
          ),
        )}
      </div>
      {selected && selected.accounts.length > 1 && (
        <details key={selected.id} className="text-xs text-ink-muted">
          <summary className="cursor-pointer py-1">
            {trx(
              "{0} · refine",
              value.startsWith("bank:")
                ? tr("All {0} accounts of {1}", selected.accounts.length, selected.name)
                : selected.accounts.find((a) => String(a.id) === value)?.name,
            )}
          </summary>
          <div className="flex flex-wrap gap-2 pt-2">
            {pill(`bank:${selected.id}`, tr("Together"), value.startsWith("bank:"))}
            {selected.accounts.map((a) => pill(String(a.id), a.name, String(a.id) === value))}
          </div>
        </details>
      )}
    </div>
  );
}
