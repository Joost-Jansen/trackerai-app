import type { Account } from "./money";
export function accountGroups(accounts: Account[]) {
  const groups = new Map<string, { id: string; name: string; accounts: Account[] }>();
  for (const r of accounts) {
    // Generic/manual providers don't establish that accounts belong to one bank.
    const bank = r.kind === "bank" && !["manual", "enablebanking"].includes(r.provider);
    const id = bank ? `${r.provider}:${r.currency}` : `account:${r.id}`;
    const name = bank ? (({ ing: "ING", bunq: "bunq", revolut: "Revolut" } as Record<string, string>)[r.provider] ?? r.provider) : r.name;
    if (!groups.has(id)) groups.set(id, { id, name, accounts: [] });
    groups.get(id)!.accounts.push(r);
  }
  return [...groups.values()];
}
