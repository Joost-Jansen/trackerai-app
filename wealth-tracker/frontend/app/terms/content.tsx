"use client";

// The text of the page, in the reader's language (lib/i18n): a client component, because the server only renders
// Dutch. page.tsx around it carries the metadata.

import { useEffect } from "react";
import { APP } from "@/lib/app";
import Link from "next/link";
import { tr, trx } from "@/lib/i18n";

export default function TermsPageContent() {
  useEffect(() => {
    document.title = tr("Terms · {0}", APP.name);
  }, []);

  return (
    <main className="mx-auto flex min-h-screen max-w-[680px] flex-col gap-8 p-6 py-12">
      <div className="flex flex-col gap-1.5">
        <h1 className="font-display text-[34px] font-light leading-tight tracking-[-0.03em]">{tr("Terms")}</h1>
        <p className="text-[13px] text-ink-muted">{tr("Last updated on 13 September 2026.")}</p>
      </div>

      <ul className="flex list-disc flex-col gap-3 pl-5 text-[14px] leading-relaxed">
        <li>{trx("{0} is a personal overview, not financial advice. You make the decisions about your money yourself.", APP.name)}</li>
        <li>{tr("The figures come from what you upload, enter or connect, and from public prices. They can be incomplete or wrong; check what matters with your bank or broker.")}</li>
        <li>{tr("A bank connection is read-only. The app cannot make payments or change anything on your account.")}</li>
        <li>{tr("You use the app at your own risk. The admin of this installation can change or stop the service.")}</li>
        <li>{trx("How your data is handled is in the {0}.", <Link href="/privacy" className="underline underline-offset-4">{tr("privacy statement")}</Link>)}</li>
      </ul>

      <p className="text-[13px] text-ink-muted">
        <Link href="/login" className="underline underline-offset-4">{tr("Log in")}</Link>
      </p>
    </main>
  );
}
