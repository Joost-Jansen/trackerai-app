"use client";

// The text of the page, in the reader's language (lib/i18n): a client component, because the server only renders
// Dutch. page.tsx around it carries the metadata.

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { APP } from "@/lib/app";
import Link from "next/link";
import { tr, trx } from "@/lib/i18n";


function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="font-display text-[19px] font-normal tracking-[-0.01em]">{title}</h2>
      <div className="flex flex-col gap-2 text-[14px] leading-relaxed">{children}</div>
    </section>
  );
}

type Operator = { controller: string | null; contact: string | null };

export default function PrivacyPageContent() {
  // Who runs this installation comes from the server (PRIVACY_CONTROLLER, PRIVACY_CONTACT).
  const [operator, setOperator] = useState<Operator | null>(null);
  useEffect(() => {
    document.title = `Privacy · ${APP.name}`;
    api.get<Operator>("/api/privacy").then(setOperator, () => setOperator({ controller: null, contact: null }));
  }, []);

  return (
    <main className="mx-auto flex min-h-screen max-w-[680px] flex-col gap-8 p-6 py-12">
      <div className="flex flex-col gap-1.5">
        <h1 className="font-display text-[34px] font-light leading-tight tracking-[-0.03em]">Privacy</h1>
        <p className="text-[13px] text-ink-muted">{tr("Last updated on 9 October 2026.")}</p>
      </div>

      <p className="text-[14px] leading-relaxed">{trx("{0} is a personal overview of your investments, accounts, spending and net worth. This installation is run by whoever hosts it (“the admin”). Below is which data the app uses, what for, and what you can do with it.", APP.name)}</p>

      <Block title={tr("Who is responsible")}>
        <p>{operator?.controller
          ? trx("This installation is run by {0}, who is responsible for your data here (the controller under the GDPR).", <strong>{operator.controller}</strong>)
          : tr("This installation is run by its admin, who is responsible for your data here (the controller under the GDPR).")}</p>
        {operator?.contact && <p>{trx("Questions or requests about your data: {0}.", <span className="font-medium">{operator.contact}</span>)}</p>}
      </Block>

      <Block title={tr("Which data")}>
        <ul className="list-disc pl-5">
          <li>{tr("Your account: username and your password, which is only stored as a hash.")}</li>
          <li>{tr("How often you use the app: per day the number of pages you opened, never which ones, so the administrator sees how much it is used. It goes when your account is deleted.")}</li>
          <li>{tr("What you upload or enter yourself: exports from your broker and your bank, balances, manual transactions, categories, rules and budgets.")}</li>
          <li>{tr("If you connect a bank account: for the accounts you give consent for, the account number, the balances and the transactions (date, amount, counterparty and description). The connection is read-only: the app cannot make payments.")}</li>
          <li>{tr("If you connect an AI assistant (Settings, Agents): an agent token, of which only a hash is stored.")}</li>
          <li>{tr("Feedback you send: your message, a screenshot of the page (taken when you open the feedback; you see it and can remove it before sending), the page you were on, your browser, screen size and recent error messages. Only the admin sees it, and the AI assistant the admin uses to work on it.")}</li>
        </ul>
      </Block>

      <Block title={tr("What for")}>
        <p>{tr("Only to show you your own overview: your net worth over time, your spending per category and your investments. No advertising, no profiling. Data is not sold and not shared with anyone other than those named below.")}</p>
      </Block>

      <Block title={tr("Where and who has access")}>
        <p>{tr("Each user has their own database on the server of this installation. Other users cannot see your data. As host, the admin has technical access to the server.")}</p>
      </Block>

      <Block title={tr("Other parties")}>
        <ul className="list-disc pl-5">
          <li>{trx("{0}, a licensed provider under the European payment services directive (PSD2), provides the bank connection. Through them the app fetches your balances and transactions, only with your consent.", <strong>Enable Banking</strong>)}</li>
          <li>{trx("{0}, where you give that consent and can revoke it again.", <strong>{tr("Your bank")}</strong>)}</li>
          <li>{trx("{0} (such as Yahoo Finance and OpenFIGI) only receive the codes of securities (ISIN or ticker) to request a price, no personal data.", <strong>{tr("Price providers")}</strong>)}</li>
          <li>{trx("{0} (for example Claude via MCP) sees the data it requests with your token, under that provider's terms. A read-only token cannot change anything; you revoke a token under Settings, Agents.", <strong>{tr("An AI assistant you connect yourself")}</strong>)}</li>
          <li>{trx("{0}, only if you turn on the AI label suggestions yourself (off by default, per account): for transactions the rules couldn't label, name, description, amount and date go to Claude, Anthropic's AI, for a suggestion; when looking thoroughly also more descriptions per counterparty. Account, card and reference numbers are removed before sending. Anthropic processes them under its API terms. Turning it off stops the sending and removes its labels.", <strong>Anthropic</strong>)}</li>
          <li>{trx("{0}, the admin's push service: hears that feedback came in, never what's in it.", <strong>ntfy</strong>)}</li>
          <li>{trx("{0} the server runs on.", <strong>{tr("The hosting provider")}</strong>)}</li>
        </ul>
      </Block>

      <Block title={tr("How long")}>
        <p>{tr("Until you delete them or have your account deleted. A bank connection is valid for a limited time (under European rules about 180 days at most) and you can revoke it earlier at any moment at your bank or at Enable Banking.")}</p>
      </Block>

      <Block title={tr("What you can do")}>
        <ul className="list-disc pl-5">
          <li>{tr("You delete accounts, balances and manual transactions yourself in the app.")}</li>
          <li>{tr("Under Settings, Your data you download everything the app holds for you (access and portability), and you delete your whole account with all its data yourself.")}</li>
          <li>{tr("For anything else, such as a correction, contact the admin of this installation.")}</li>
        </ul>
      </Block>

      <Block title={tr("Security")}>
        <p>{tr("The connection runs over HTTPS, passwords and agent tokens are only stored as a hash, the keys of a bank connection are stored encrypted, two-step login is available, and the bank connection can only read.")}</p>
      </Block>

      <p className="text-[13px] text-ink-muted">
        <Link href="/terms" className="underline underline-offset-4">{tr("Terms")}</Link>
        {" · "}
        <Link href="/login" className="underline underline-offset-4">{tr("Log in")}</Link>
      </p>
    </main>
  );
}
