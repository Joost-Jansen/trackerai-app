// Where a user stands: what they track, whether the welcome flow is done, and per
// part what is already there. Stored with the account; see onboarding.py.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { tr } from "@/lib/i18n";

export type Choice = "investments" | "money" | "both";
/** How bank data comes in: exports only, or exports plus the automatic bank connection. */
export type BankChoice = "upload" | "connect";

export type OnboardingStatus = {
  portfolio: { transactions: number; dividends: number };
  money: {
    accounts: number;
    without_balance: string[];
    bank_transactions: number;
    linked: boolean;
    unlabelled: number;
  };
};

export type Onboarding = {
  choice: Choice | null;
  bank: BankChoice | null;
  done: boolean;
  step: number;
  status: OnboardingStatus;
  /** Is Money on for this account (beta flag)? If not, the choice is always "investments". */
  money: boolean;
};

export function useOnboarding(enabled = true) {
  return useQuery({ queryKey: ["onboarding"], queryFn: () => api.get<Onboarding>("/api/onboarding"), enabled });
}

export function useSaveOnboarding() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (fields: { choice?: Choice | null; bank?: BankChoice | null; done?: boolean; step?: number }) => api.put<Onboarding>("/api/onboarding", fields),
    onSuccess: (d) => qc.setQueryData(["onboarding"], d),
  });
}

/** Does this part belong to what you track? Without a choice: everything. */
export function isIncluded(choice: Choice | null | undefined, part: "investments" | "money"): boolean {
  return !choice || choice === "both" || choice === part;
}

export const CHOICES: { id: Choice; title: string; explanation: string }[] = [
  { id: "investments", title: tr("My DeGiro portfolio"), explanation: tr("Your positions, returns and dividends.") },
  { id: "money", title: tr("My money"), explanation: tr("Bank and savings accounts, spending, debts and net worth.") },
  { id: "both", title: tr("Both"), explanation: tr("Your complete net worth, from investments to bank.") },
];
