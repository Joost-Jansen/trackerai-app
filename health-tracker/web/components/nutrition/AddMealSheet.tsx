"use client";

// "Maaltijd toevoegen": four ways in, each ending in the meal editor (MealEditor) where you check and save.
//   Foto     the camera or the library; the photo goes (smaller, without metadata) to the API, which asks Claude and
//            returns a draft. Only when photo analysis is on (Zones en profiel).
//   Zoeken   NEVO, your own foods and what you ate lately.
//   Barcode  a package's EAN from Open Food Facts: read from a photo where the browser can, else typed.
//   Opnieuw  your favourites and the same moment yesterday, in one tap.
// `start="photo"` skips the choice and opens the camera at once (the floating camera button on the Day tab).

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Button, Dialog, Input } from "@/components/ds";
import MealEditor from "@/components/nutrition/MealEditor";
import { fromFood, fromMeal, fromTemplate, photoStart } from "@/components/nutrition/drafts";
import { canReadBarcodes, photoTime, preparePhoto, readBarcode } from "@/components/nutrition/photo";
import { api } from "@/lib/api";
import { errorText, useLocale, useT } from "@/lib/i18n";
import { momentAt, nowHHMM, type EditorStart, type Food, type Meal, type PhotoDraft, type Template } from "@/lib/nutrition";

type Step = "choose" | "analysing" | "barcode" | "again";

function Option({ title, text, onClick, disabled = false }: { title: string; text: string; onClick: () => void; disabled?: boolean }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled}
      className="flex flex-col items-start gap-0.5 rounded-md border border-border px-4 py-3 text-left hover:bg-[var(--surface-sunken)] disabled:opacity-50">
      <span className="text-[14px] font-medium">{title}</span>
      <span className="text-[12px] text-ink-muted">{text}</span>
    </button>
  );
}

function Again({ day, onPick }: { day: string; onPick: (start: EditorStart) => void }) {
  const t = useT().nutrition.add;
  const moment = momentAt(nowHHMM());
  const q = useQuery({
    queryKey: ["nutrition-again", day, moment],
    queryFn: () => api.get<{ favourites: Template[]; yesterday: Meal[] }>(`/api/nutrition/again?day=${day}&moment=${moment}`),
  });
  if (q.isLoading) return <p className="text-[13px] text-ink-muted">{t.loading}</p>;
  const favourites = q.data?.favourites ?? [];
  const yesterday = q.data?.yesterday ?? [];
  if (!favourites.length && !yesterday.length) return <p className="text-[13px] text-ink-muted">{t.againEmpty}</p>;
  return (
    <div className="flex flex-col gap-3">
      {yesterday.length > 0 && (
        <section className="flex flex-col gap-1.5">
          <h3 className="text-[12px] font-medium text-ink-muted">{t.likeYesterday}</h3>
          {yesterday.map((m) => (
            <Option key={`y${m.id}`} title={m.items.map((i) => i.name).join(", ")} text={`${m.eaten_at} · ${Math.round(m.totals.energy_kcal)} kcal`}
              onClick={() => onPick({ input: "repeat", items: fromMeal(m, false), moment: m.moment })} />
          ))}
        </section>
      )}
      {favourites.length > 0 && (
        <section className="flex flex-col gap-1.5">
          <h3 className="text-[12px] font-medium text-ink-muted">{t.favourites}</h3>
          {favourites.map((f) => (
            <Option key={`f${f.id}`} title={f.name} text={f.items.map((i) => i.name).join(", ")}
              onClick={() => onPick({ input: "repeat", items: fromTemplate(f), moment: f.moment })} />
          ))}
        </section>
      )}
    </div>
  );
}

function Barcode({ onFound }: { onFound: (food: Food) => void }) {
  const tt = useT();
  const t = tt.nutrition.add;
  const [ean, setEan] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const file = useRef<HTMLInputElement>(null);

  async function look(code: string) {
    setBusy(true);
    setError(null);
    try {
      onFound(await api.get<Food>(`/api/nutrition/foods/barcode/${encodeURIComponent(code)}`));
    } catch (err) {
      setError(errorText(err, tt, t.failed));
    } finally {
      setBusy(false);
    }
  }

  async function scanned(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    const code = await readBarcode(f).catch(() => null);
    if (code) {
      setEan(code);
      await look(code);
    } else setError(t.noBarcode);
  }

  return (
    <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); if (ean.trim()) look(ean.trim()); }}>
      {canReadBarcodes() && (
        <>
          <input ref={file} type="file" accept="image/*" capture="environment" className="hidden" onChange={scanned} />
          <Button variant="secondary" onClick={() => file.current?.click()} disabled={busy}>{t.scan}</Button>
        </>
      )}
      <Input label={t.ean} inputMode="numeric" autoFocus={!canReadBarcodes()} value={ean} onChange={(e) => setEan(e.target.value.replace(/\D/g, ""))} maxLength={14} />
      <Button variant="primary" type="submit" disabled={busy || ean.length < 8}>{t.lookUp}</Button>
      <p className="text-[11.5px] text-ink-muted">{t.offNote}</p>
      {error && <p className="text-[12.5px] text-loss" role="alert">{error}</p>}
    </form>
  );
}

export default function AddMealSheet({ day, ai, onClose, start }: { day: string; ai: boolean; onClose: () => void; start?: "photo" }) {
  const tt = useT();
  const t = tt.nutrition.add;
  const { locale } = useLocale();
  const [step, setStep] = useState<Step>("choose");
  const [editor, setEditor] = useState<EditorStart | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const camera = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (start === "photo") camera.current?.click();
  }, [start]);
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);

  async function photo(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setError(null);
    setPreview(URL.createObjectURL(file));
    setStep("analysing");
    try {
      const draft = await api.upload<PhotoDraft>("/api/nutrition/photo", await preparePhoto(file));
      setEditor(photoStart(draft, draft.photo_id ? null : URL.createObjectURL(file), locale, photoTime(file) ?? undefined));
    } catch (err) {
      setError(errorText(err, tt, t.failed));
      setStep("choose");
    }
  }

  if (editor) return <MealEditor day={day} start={editor} onClose={onClose} />;

  const title = step === "analysing" ? t.analysing : step === "barcode" ? t.barcode : step === "again" ? t.again : tt.nutrition.editor.addTitle;
  return (
    <Dialog open onClose={onClose} title={title}
      actions={<Button variant="ghost" onClick={step === "choose" || step === "analysing" ? onClose : () => setStep("choose")}>{step === "choose" || step === "analysing" ? t.close : t.back}</Button>}>
      <input ref={camera} type="file" accept="image/*" capture="environment" className="hidden" onChange={photo} />
      {step === "choose" && (
        <div className="grid gap-2 sm:grid-cols-2">
          <Option title={t.photo} text={ai ? t.photoText : t.photoOff} onClick={() => camera.current?.click()} disabled={!ai} />
          <Option title={t.search} text={t.searchText} onClick={() => setEditor({ input: "search", items: [] })} />
          <Option title={t.barcode} text={t.barcodeText} onClick={() => setStep("barcode")} />
          <Option title={t.again} text={t.againText} onClick={() => setStep("again")} />
          {!ai && <p className="text-[11.5px] text-ink-muted sm:col-span-2"><Link href="/settings/zones/#nutrition" className="underline underline-offset-4">{t.turnOn}</Link></p>}
          {error && <p className="text-[12.5px] text-loss sm:col-span-2" role="alert">{error}</p>}
        </div>
      )}
      {step === "analysing" && (
        <div className="flex flex-col items-center gap-3" aria-busy="true">
          {/* eslint-disable-next-line @next/next/no-img-element -- a local preview of the photo being analysed */}
          {preview && <img src={preview} alt="" className="max-h-48 w-full rounded-md object-cover opacity-80" />}
          <p className="text-[13px] text-ink-muted" aria-live="polite">{t.looking}</p>
          <div className="flex w-full flex-col gap-2">{[0, 1, 2].map((i) => <span key={i} className="h-8 animate-pulse rounded bg-[var(--surface-sunken)]" />)}</div>
        </div>
      )}
      {step === "barcode" && <Barcode onFound={(food) => setEditor({ input: "barcode", items: [fromFood(food, locale)] })} />}
      {step === "again" && <Again day={day} onPick={setEditor} />}
    </Dialog>
  );
}
