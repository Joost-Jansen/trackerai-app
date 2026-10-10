"use client";

// Settings → Money: where your own share of shared costs counts.
//
// Money that passes through you for a group ("Niet meetellen") is not your
// spending, but your own share in it is. The backend works that share out
// (shared_costs.py); here you say in which spending category it lands, or that it
// counts nowhere. Hidden when the money part of the app is off for this account.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { Select } from "@/components/ds";
import type { Category } from "@/lib/money";
import { tr } from "@/lib/i18n";

type Setting = { category: string | null; default: string };

export default function SharedCostsChoice() {
  const qc = useQueryClient();
  const setting = useQuery({
    queryKey: ["shared-costs"],
    queryFn: () => api.get<Setting>("/api/spending/shared-costs"),
    retry: false,
  });
  const categories = useQuery({
    queryKey: ["categories"],
    queryFn: () => api.get<{ categories: Category[] }>("/api/categories"),
    retry: false,
  });
  const put = useMutation({
    mutationFn: (category: string | null) => api.put<Setting>("/api/spending/shared-costs", { category }),
    onSuccess: (d) => {
      qc.setQueryData(["shared-costs"], d);
      // Spending and net worth both add it up.
      qc.invalidateQueries({ queryKey: ["bank_transactions"] });
      qc.invalidateQueries({ queryKey: ["net_worth"] });
    },
  });
  if (!setting.data || !categories.data) return null;
  const spending = categories.data.categories.filter((c) => c.type === "EXPENSE");
  const NOWHERE = "";

  return (
    <div className="flex flex-col gap-1">
      <Select
        aria-label={tr("Your share of shared costs counts as")}
        value={setting.data.category ?? NOWHERE}
        disabled={put.isPending}
        onChange={(e) => put.mutate(e.target.value || null)}
      >
        <option value={NOWHERE}>{tr("Don't count it")}</option>
        {spending.map((c) => <option key={c.id} value={c.name}>{c.group_name} · {c.name}</option>)}
      </Select>
      {put.isError && (
        <span className="text-xs" style={{ color: "var(--text-loss)" }}>
          {put.error instanceof ApiError ? put.error.message : tr("Couldn't save. Try again.")}
        </span>
      )}
    </div>
  );
}
