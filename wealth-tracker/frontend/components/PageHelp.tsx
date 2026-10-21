"use client";

// The "?" next to the page title — the largest of the three help levels.
//
//   ?  in the top bar      → what this screen is and where its figures come from
//   i  on a section header → what *this* list or chart shows, in one or two sentences
//   i  next to a number    → what *this* number measures
//
// One glyph family, one gesture (clicking), three levels of scale. The content
// is in lib/help.tsx; this component is only the button and the dialog around
// it.
//
// A dialog and not a popover, unlike InfoPopover: it is about four to six
// paragraphs, and cramming those into a 320px panel gives a scrollable postage
// stamp on a phone. Meridian allows a card where a boundary really exists — a
// dialog is exactly that case.

import { useState } from "react";
import { usePathname } from "next/navigation";
import { helpFor } from "@/lib/help";
import { HelpIcon } from "@trackerai/ui/icons";
import { Button, ButtonLink, Dialog } from "@/components/ds";
import { tr } from "@/lib/i18n";

const MONEY = ["/net-worth", "/accounts", "/spending", "/categories"];

/** The manual in Help that belongs to this screen. */
function helpPart(pathname: string): string {
  if (pathname === "/help" || pathname.startsWith("/help/")) return "/help";
  return MONEY.some((p) => pathname === p || pathname.startsWith(`${p}/`)) ? "/help/money" : "/help/portfolio";
}

export default function PageHelp() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const help = helpFor(pathname);

  // No help for this address means no button. A "?" that opens an empty dialog is
  // worse than a bar without "?".
  if (!help) return null;

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={tr("Explanation of this screen")}
        aria-haspopup="dialog"
        // The same sizing as InfoPopover's "i": a 23px hitbox that takes back its drawn
        // 15px through the negative margin, so the glyph next to the title does not
        // stand there as a button but a thumb can still land on it.
        className={`-m-1 grid h-[23px] w-[23px] flex-none place-items-center rounded-full transition-colors hover:text-brand ${
          open ? "text-brand" : "text-ink-muted"
        }`}
      >
        <HelpIcon className="h-[15px] w-[15px]" />
      </button>

      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title={help.title}
        actions={
          <>
            {/* This is the short explanation; the guide for the same part is in Help. */}
            <ButtonLink href={helpPart(pathname)} variant="ghost" onClick={() => setOpen(false)}>
              {tr("More in Help")}
            </ButtonLink>
            <Button variant="secondary" onClick={() => setOpen(false)}>
              {tr("Close")}
            </Button>
          </>
        }
      >
        {/* The design's reading measure, and the body size: this is editorial text, not chrome, so
            15px and not 13. It never gets wider than the ~440px of the dialog anyway. */}
        <div className="flex max-h-[65vh] flex-col gap-3.5 overflow-y-auto text-[15px] leading-relaxed text-ink-muted">{help.body}</div>
      </Dialog>
    </>
  );
}
