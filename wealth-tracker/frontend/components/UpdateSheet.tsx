"use client";

// The "Bijwerken" slide-over (mockup: "Gegevens bijwerken"). Everything that
// refreshes data lives here — price refresh, the two DeGiro imports and the
// bank exports —
// reachable from the header on every page, replacing the three loose buttons
// the old dashboard header carried. Uploading is monthly maintenance, not a
// dashboard widget, hence chrome rather than cockpit.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { PricesRefresh, PricesStatus } from "@/lib/dashboard";
import { fmtRelative } from "@/lib/format";
import { CloseIcon, RefreshIcon, UploadIcon } from "@trackerai/ui/icons";
import { BANKS, type Bank } from "@/lib/guide";
import { StepPlanDialog } from "@/components/steps/StepPlan";
import { EXPORT_ROUTES } from "@/components/steps/money";
import Link from "next/link";
import { Button, IconButton } from "@/components/ds";
import type { BankImportResult, ConnectionStatus, FetchReport } from "@/lib/money";
import { locale, tr, trx } from "@/lib/i18n";

type UploadResult = {
  filename: string;
  saved: number;
  skipped: number;
  /** Payments this file holds no exchange rate for, so they are not imported.
   *  Named rather than folded into `skipped`: a skipped duplicate changes
   *  nothing, while these are euros missing from every dividend total. */
  unconverted?: { date: string; name: string; currency: string; amount: number }[];
  /** Transaction rows whose number of units could not be established, so they
   *  are not imported. Named for the same reason as `unconverted`: these are
   *  positions missing from the portfolio, not harmless duplicates. */
  unparsed?: { date: string | null; name: string | null; isin: string; reason: string }[];
};

function useUpload(endpoint: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (files: FileList | File[]) => {
      const form = new FormData();
      Array.from(files).forEach((f) => form.append("files", f));
      const res = await fetch(endpoint, { method: "POST", credentials: "include", body: form, headers: { "X-Locale": locale } });
      if (!res.ok) {
        // The backend names what is wrong with the file (422); api.ts does the
        // same unwrapping, but FormData can't go through it.
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || tr("Upload failed. Try again."));
      }
      return res.json() as Promise<{ results: UploadResult[] }>;
    },
    onSuccess: () => queryClient.invalidateQueries(),
  });
}

/** The dashed upload target: click to pick files, or drop them on it. Shared by
 *  the DeGiro and the bank imports, which differ only in what they report. */
function DropButton({
  title,
  subtitle,
  onFiles,
}: {
  title: string;
  subtitle: string;
  onFiles: (files: FileList | File[]) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  return (
    <>
      <input
        ref={input}
        type="file"
        // Wide on purpose, and every entry earns its place. A bare `accept`
        // of ".xlsx" greyed out the DeGiro export in the iOS Files picker —
        // DeGiro writes a technically sloppy package ([Content_Types].xml is
        // not the first zip part, no default styles), so iOS does not
        // confidently type it as a spreadsheet, and on a phone there is no
        // "show all files" escape like a desktop dialog has. But dropping
        // `accept` entirely made iOS offer Fotobibliotheek and Camera, which
        // can only ever produce an upload the backend rejects.
        //
        // So: cover all three things iOS might decide the file is — a real
        // spreadsheet, the zip it physically is, or unlabelled data — while
        // naming no image or video type, which is what hides the photo
        // options. Narrow this and the mobile upload breaks again.
        accept={[
          ".xlsx",
          ".csv",
          "text/csv",
          ".xls",
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          "application/vnd.ms-excel",
          "application/zip",
          "application/octet-stream",
        ].join(",")}
        multiple
        className="hidden"
        onChange={(e) => {
          // Copy before clearing: a FileList is *live* — resetting the input
          // empties it, and the mutation reads it a microtask later. Cleared
          // first, the request went out with zero files (a 422 this exact
          // flow caught).
          if (e.target.files?.length) onFiles(Array.from(e.target.files));
          e.target.value = "";
        }}
      />
      <button
        type="button"
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          if (e.dataTransfer.files?.length) onFiles(e.dataTransfer.files);
        }}
        className="mb-2.5 flex w-full items-center gap-3 rounded-md border border-dashed p-3.5 text-left transition-colors"
        style={{
          borderColor: dragOver ? "var(--brand-500)" : "var(--border-strong)",
          background: dragOver ? "var(--surface-hover)" : undefined,
        }}
      >
        <UploadIcon className="h-4 w-4 flex-none" style={{ color: "var(--text-faint)" }} />
        <span className="min-w-0">
          <span className="block text-[13.5px] font-medium">{title}</span>
          <span className="mt-px block text-[11.5px] text-ink-muted">{subtitle}</span>
        </span>
      </button>
    </>
  );
}

function Dropzone({
  title,
  subtitle,
  onFiles,
  state,
}: {
  title: string;
  subtitle: string;
  onFiles: (files: FileList | File[]) => void;
  state: ReturnType<typeof useUpload>;
}) {
  return (
    <div>
      <DropButton title={title} subtitle={subtitle} onFiles={onFiles} />
      {state.isPending && <p className="mb-2 text-xs text-ink-muted">{tr("Processing…")}</p>}
      {state.isError && <p className="mb-2 text-xs" style={{ color: "var(--text-loss)" }}>{state.error.message}</p>}
      {state.data && (
        <p className="mb-2 text-xs text-ink-muted">
          {state.data.results.map((r) => (
            <span key={r.filename} className="block">
              {r.filename}:{" "}
              <b className="num" style={{ color: "var(--text-gain)" }}>{trx("{0} new", r.saved)}</b>
              {" · "}
              <span className="num">{trx("{0} skipped", r.skipped)}</span>
              {r.unparsed && r.unparsed.length > 0 && (
                <span className="mt-0.5 block" style={{ color: "var(--text-loss)" }}>{trx("{0} {1} not read: the quantity is missing and can't be derived from the price: {2}.", <span className="num">{r.unparsed.length}</span>, r.unparsed.length === 1 ? tr("line") : tr("lines"), Array.from(new Set(r.unparsed.map((u) => u.name ?? u.isin))).join(", "))}</span>
              )}
              {r.unconverted && r.unconverted.length > 0 && (
                <span className="mt-0.5 block" style={{ color: "var(--text-loss)" }}>{trx("{0} {1} in {2} not counted: the exchange rate isn't in this file. Export a period that also contains the currency exchange.", <span className="num">{r.unconverted.length}</span>, r.unconverted.length === 1 ? tr("payout") : tr("payouts"), Array.from(new Set(r.unconverted.map((u) => u.currency))).join(", "))}</span>
              )}
            </span>
          ))}
        </p>
      )}
    </div>
  );
}

function BankRule({ r }: { r: BankImportResult }) {
  if ("error" in r) {
    return (
      <span className="block" style={{ color: "var(--text-loss)" }}>
        {r.file}: {r.error}
      </span>
    );
  }
  const created = r.accounts.filter((x) => x.created).length;
  return (
    <span className="block">
      {r.file}:{" "}
      {r.kind === "balances" ? (
        <>{trx("balance per day for {0} {1}", <b className="num text-text">{r.accounts.length}</b>, r.accounts.length === 1 ? tr("account") : tr("accounts"))}</>
      ) : (
        <>
          <b className="num" style={{ color: "var(--text-gain)" }}>{trx("{0} new", r.saved)}</b>
          {" · "}
          <span className="num">{trx("{0} skipped", r.skipped)}</span>
        </>
      )}
      {r.balances > 0 && (
        <>{" "}{trx("· balance on {0} {1}", <span className="num">{r.balances}</span>, r.balances === 1 ? tr("day") : tr("days"))}</>
      )}
      {created > 0 && (
        <>{" "}{trx("· {0} {1} created", created, created === 1 ? tr("account") : tr("accounts"))}</>
      )}
      {r.unreadable.length > 0 && (
        <span className="mt-0.5 block" style={{ color: "var(--text-loss)" }}>{trx("{0} {1} not read (first: line {2}, {3})", <span className="num">{r.unreadable.length}</span>, r.unreadable.length === 1 ? tr("line") : tr("lines"), r.unreadable[0].line_number, r.unreadable[0].reason)}</span>
      )}
    </span>
  );
}

/**
 * Bank exports: current and savings accounts, and balance overviews. Several
 *  files at once; per file a line with what it delivered.
 */
function BankImport() {
  const [bank, setBank] = useState<Bank>("ing");
  const [explanation, setExplanation] = useState(false);
  const queryClient = useQueryClient();
  const upload = useMutation({
    mutationFn: async (files: FileList | File[]) => {
      const form = new FormData();
      Array.from(files).forEach((f) => form.append("files", f));
      const res = await fetch("/api/uploads/bank", { method: "POST", credentials: "include", body: form, headers: { "X-Locale": locale } });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || tr("Upload failed. Try again."));
      return body as { results: BankImportResult[] };
    },
    onSuccess: () => queryClient.invalidateQueries(),
  });
  const chosen = BANKS.find((b) => b.id === bank) ?? BANKS[0];

  return (
    <>
      <div className="ds-section__head mb-4 mt-7">
        <span className="ds-section__label">{tr("Import from your bank")}</span>
      </div>
      <div className="mb-3 flex gap-1" role="group" aria-label={tr("Which bank")}>
        {BANKS.map((b) => (
          <Button
            key={b.id}
            size="sm"
            variant={b.id === bank ? "primary" : "ghost"}
            aria-pressed={b.id === bank}
            onClick={() => setBank(b.id)}
          >
            {b.name}
          </Button>
        ))}
      </div>
      <p className="mb-3 text-xs text-ink-muted">
        {chosen.note}{" "}
        <button type="button" onClick={() => setExplanation(true)}
          className="underline decoration-[var(--border-strong)] underline-offset-2 hover:text-text">{tr("How do I export this?")}</button>
      </p>
      <StepPlanDialog open={explanation} onClose={() => setExplanation(false)} title={tr("Make a bank export")}
        routes={EXPORT_ROUTES} begin={bank} chooseLabel="Mijn bank:" />
      <DropButton
        title={`${chosen.name}-export`}
        subtitle={tr(".csv · several files at once is fine")}
        onFiles={(f) => upload.mutate(f)}
      />
      {upload.isPending && <p className="mb-2 text-xs text-ink-muted">{tr("Processing…")}</p>}
      {upload.isError && (
        <p className="mb-2 text-xs" style={{ color: "var(--text-loss)" }}>{upload.error.message}</p>
      )}
      {upload.data && (
        <p className="mb-2 text-xs text-ink-muted">
          {upload.data.results.map((r, i) => (
            <BankRule key={`${r.file}-${i}`} r={r} />
          ))}
        </p>
      )}
    </>
  );
}

/**
 * A connected bank: fetch new transactions and balance without an export.
 *  Not connected yet: a link to the step-by-step plan.
 */
function ConnectionFetch({ onNavigate }: { onNavigate: () => void }) {
  const queryClient = useQueryClient();
  const status = useQuery({
    queryKey: ["connections"],
    queryFn: () => api.get<ConnectionStatus>("/api/connections"),
  });
  const retrieve = useMutation({
    mutationFn: () => api.post<FetchReport>("/api/connections/enablebanking/fetch"),
    onSuccess: () => queryClient.invalidateQueries(),
  });
  const active = (status.data?.consents ?? []).filter((t) => t.status === "active");
  const banks = [...new Set(active.map((t) => t.bank))].join(", ");

  return (
    <>
      <div className="ds-section__head mb-4 mt-7">
        <span className="ds-section__label">{tr("Bank connection")}</span>
        <Link
          href="/accounts/connect"
          onClick={onNavigate}
          className="ds-section__meta underline decoration-[var(--border-strong)] underline-offset-2 hover:text-text"
        >
          {status.data?.configured ? tr("Manage") : tr("Set up")}
        </Link>
      </div>
      {active.length > 0 ? (
        <>
          <Button
            variant="secondary"
            block
            onClick={() => retrieve.mutate()}
            disabled={retrieve.isPending}
            icon={<RefreshIcon className={`h-4 w-4 ${retrieve.isPending ? "animate-spin" : ""}`} />}
          >
            {retrieve.isPending ? tr("Fetching…") : tr("Fetch now from {0}", banks)}
          </Button>
          {retrieve.data && (
            <p className="mt-2 text-xs text-ink-muted">{trx("{0} · balance of {1} {2} updated{3}", <b className="num" style={{ color: "var(--text-gain)" }}>{trx("{0} new", retrieve.data.added)}</b>, retrieve.data.balances, retrieve.data.balances === 1 ? tr("account") : tr("accounts"), retrieve.data.errors.map((f) => (
                <span key={f} className="mt-0.5 block" style={{ color: "var(--text-loss)" }}>{f}</span>
              )))}</p>
          )}
          {retrieve.isError && (
            <p className="mt-2 text-xs" style={{ color: "var(--text-loss)" }}>{(retrieve.error as Error).message}</p>
          )}
        </>
      ) : (
        <p className="text-xs text-ink-muted">{trx("Connect your bank to fetch transactions and balance automatically, without exports. {0}", <Link href="/accounts/connect" onClick={onNavigate} className="underline underline-offset-4">{tr("How it works →")}</Link>)}</p>
      )}
    </>
  );
}

export default function UpdateSheet({
  open,
  onClose,
  onOpenTutorial,
  money = false,
}: {
  open: boolean;
  onClose: () => void;
  onOpenTutorial?: () => void;
  /** Money beta flag: only then show the bank connection and the bank exports. */
  money?: boolean;
}) {
  const queryClient = useQueryClient();
  const panel = useRef<HTMLDivElement>(null);

  const { data: status } = useQuery({
    queryKey: ["prices-status"],
    queryFn: () => api.get<PricesStatus>("/api/prices/status"),
    enabled: open,
  });

  const refresh = useMutation({
    mutationFn: () => api.post<PricesRefresh>("/api/prices/refresh"),
    onSuccess: () => queryClient.invalidateQueries(),
  });

  const uploadTransactions = useUpload("/api/uploads/transactions");
  const uploadDividends = useUpload("/api/uploads/dividends");

  const close = useCallback(() => {
    // A price refresh keeps running server-side; closing mid-flight is fine.
    onClose();
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("keydown", onKey);
    panel.current?.focus();
    // The page behind a modal sheet must not scroll along.
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, close]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label={tr("Update data")}>
      <div className="absolute inset-0 bg-black/30" onClick={close} />
      <div
        ref={panel}
        tabIndex={-1}
        // overscroll-contain: scrolling to the end of the sheet must not hand
        // the gesture to the page behind it (the body lock above stops the
        // scroll, not the rubber-band). pb-10 clears the phone's own bottom
        // browser bar from the last line of copy.
        className="absolute right-0 top-0 h-full w-full max-w-[400px] overflow-y-auto overscroll-contain p-6 pb-10 outline-none sm:pb-6"
        style={{ background: "var(--surface-card)", boxShadow: "var(--shadow-4)" }}
      >
        <div className="mb-2 flex items-center justify-between gap-3">
          <h2 className="font-display text-[21px] font-normal tracking-[-0.014em]">{tr("Update data")}</h2>
          <IconButton
            label={tr("Close")}
            onClick={close}
            icon={<CloseIcon className="h-4 w-4" />}
            className="-mr-2 flex-none"
          />
        </div>

        {/* Built on the oldest quote, not the newest: the totals are only as
            current as their stalest input, and max() let one lucky ISIN speak
            for seventeen stale ones. The newest is shown beside it only when
            the two disagree, which is exactly when a partly-failed refresh has
            happened and the gap is the thing worth seeing. */}
        <p className="mb-4 text-xs text-ink-muted">
          {status?.oldest_price ? (
            <>{trx("Prices updated {0}{1}", <b className="text-text">{fmtRelative(status.oldest_price)}</b>, status.last_updated && status.last_updated !== status.oldest_price && (
                <>{" "}{trx("· newest {0}", fmtRelative(status.last_updated))}</>
              ))}</>
          ) : (
            tr("No prices fetched yet")
          )}
          {status?.last_import && <>{" "}{trx("· last import {0}", fmtRelative(status.last_import))}</>}
        </p>

        <Button
          variant="primary"
          size="lg"
          block
          onClick={() => refresh.mutate()}
          disabled={refresh.isPending}
          icon={<RefreshIcon className={`h-4 w-4 ${refresh.isPending ? "animate-spin" : ""}`} />}
        >
          {refresh.isPending ? tr("Fetching prices…") : tr("Refresh prices")}
        </Button>
        {refresh.isError && (
          <p className="mt-2 text-xs" style={{ color: "var(--text-loss)" }}>{tr("Refreshing failed. Try again later.")}</p>
        )}
        {/* A 200 is not the same as a refresh. The endpoint answers 200 for a
            round in which Yahoo returned nothing at all, so reporting success
            on `isSuccess` alone is what put a green "Koersen bijgewerkt."
            directly under a grey "Koersen bijgewerkt 4 dagen geleden". These
            three branches say which of the three things actually happened. */}
        {refresh.isSuccess && refresh.data && (
          refresh.data.updated_count === 0 ? (
            <p className="mt-2 text-xs" style={{ color: "var(--text-loss)" }}>{tr("Not a single price fetched. The previous prices stay. Check the server's internet connection.")}</p>
          ) : refresh.data.complete ? (
            <p className="mt-2 text-xs" style={{ color: "var(--text-gain)" }}>{refresh.data.updated_count === 1 ? tr("1 price updated.") : tr("{0} prices updated.", refresh.data.updated_count)}</p>
          ) : (
            <p className="mt-2 text-xs text-warn">{trx("{0} updated, {1} failed: those still show their previous price.{2}", refresh.data.updated_count, refresh.data.failed.length + refresh.data.skipped, refresh.data.failed.length > 0 && (
                <span className="block text-ink-muted">
                  {refresh.data.failed.map((f) => f.name).join(", ")}
                </span>
              ))}</p>
          )
        )}

        {/* Een gelijnde sectie, net als op elk ander scherm. */}
        <div className="ds-section__head mb-4 mt-7">
          <span className="ds-section__label">{tr("Import from DeGiro")}</span>
          {onOpenTutorial && (
            <button
              type="button"
              onClick={() => {
                onOpenTutorial();
                close();
              }}
              className="ds-section__meta underline decoration-[var(--border-strong)] underline-offset-2 hover:text-text"
            >{tr("How do I export this?")}</button>
          )}
        </div>

        <Dropzone
          title={tr("Transactions")}
          subtitle={tr("Inbox → Transactions · .xlsx or .csv: sets positions, prices and gain")}
          onFiles={(f) => uploadTransactions.mutate(f)}
          state={uploadTransactions}
        />
        <Dropzone
          title={tr("Account statement")}
          subtitle={tr("Inbox → Account statement · .xlsx or .csv: sets your dividends")}
          onFiles={(f) => uploadDividends.mutate(f)}
          state={uploadDividends}
        />

        {money && (
          <>
            <ConnectionFetch onNavigate={close} />
            <BankImport />
          </>
        )}

        <p className="mt-3.5 text-xs text-ink-muted">{tr("Uploading again is safe: rows already saved are skipped, only new ones are added.")}</p>
        <p className="mt-2 text-xs text-ink-muted">{trx("All explanations{0} are under {1}.", money ? tr(", for investments and money,") : "", <Link href="/help" onClick={close} className="underline underline-offset-4">Help</Link>)}</p>
      </div>
    </div>
  );
}
