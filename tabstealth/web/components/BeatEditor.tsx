"use client";

// The editor for one beat: per string the fret, a grace note and the techniques; for the beat its strum and chord;
// for its bar the section. Every sign the converter writes has a control here (lib/beat.ts).

import { Button } from "@trackerai/ui/ds/Button";
import { Select } from "@trackerai/ui/ds/Field";
import { ChevronDownIcon } from "@trackerai/ui/icons";
import { nextBend, TECHNIQUES, type BeatState, type NoteState, type Strum, type Technique } from "@/lib/beat";
import { useT } from "@/lib/i18n";

const STRINGS = ["e", "B", "G", "D", "A", "E"];

// The sign on each toggle: the same marks a tab uses.
const SIGN: Record<Technique, string> = {
  hammer: "h",
  slide: "/",
  tie: "⌒",
  letRing: "LR",
  palmMute: "PM",
  ghost: "( )",
  harmonic: "◇",
  vibrato: "~",
};

function Toggle({ on, disabled, label, sign, onClick }: { on: boolean; disabled?: boolean; label: string; sign: string; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className={`h-7 min-w-[28px] rounded-sm border px-1 font-mono text-[11px] leading-none transition-colors disabled:opacity-30 ${
        on ? "border-brand bg-brand-tint text-brand" : "border-border text-ink-muted hover:border-border-strong"
      }`}
    >
      {sign}
    </button>
  );
}

export default function BeatEditor({
  title,
  value,
  onChange,
  onSave,
  onClear,
  saving,
  message,
  activeString,
  onActiveString,
  dirty,
  canUndo,
  canRedo,
  onUndo,
  onRedo,
  showKeys,
  onShowKeys,
  collapsed,
  onToggleCollapsed,
}: {
  title: string;
  value: BeatState;
  /** Gets an update function, so quick successive changes all land on the latest form. */
  onChange: (update: (v: BeatState) => BeatState) => void;
  onSave: () => void;
  onClear: () => void;
  saving: boolean;
  message: string | null;
  /** The string the keyboard types on (0 = high e). */
  activeString: number;
  onActiveString: (i: number) => void;
  dirty: boolean;
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
  showKeys: boolean;
  onShowKeys: () => void;
  /** Folded to its title row (narrow screens only; wide screens always show it all). */
  collapsed: boolean;
  onToggleCollapsed: () => void;
}) {
  const t = useT();
  const setNote = (i: number, patch: Partial<NoteState>) => {
    onChange((v) => ({ ...v, notes: v.notes.map((n, k) => (k === i ? { ...n, ...patch } : n)) }));
  };
  const input = "ds-input !h-7 !px-1 text-center font-mono text-xs";

  return (
    <section className="rounded border border-border bg-surface p-3 sm:p-4">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onSave();
        }}
      >
        <div className="flex items-center gap-2">
          <h2 className="mr-auto text-[13.5px] font-semibold tracking-[0.01em]">
            {title}
            {dirty && <span className="ml-1.5 text-brand" title={t.song.unsaved} aria-label={t.song.unsaved}>●</span>}
          </h2>
          {/* narrow screens: fold the editor to its title, so the tab keeps the room */}
          <button
            type="button"
            className="ds-btn ds-btn--ghost ds-btn--sm !px-1.5 lg:hidden"
            aria-expanded={!collapsed}
            aria-label={collapsed ? t.song.expand : t.song.collapse}
            title={collapsed ? t.song.expand : t.song.collapse}
            onClick={onToggleCollapsed}
          >
            <ChevronDownIcon className={`h-4 w-4 transition-transform ${collapsed ? "" : "rotate-180"}`} />
          </button>
        </div>
        <div className={collapsed ? "hidden lg:block" : ""}>
        <div className="mb-3 mt-2 flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1 text-[11px] text-ink-muted">
            {t.song.section}
            <input className="ds-input !h-8 w-28 text-xs" value={value.section} maxLength={60} onChange={(e) => {
              const section = e.target.value;
              onChange((v) => ({ ...v, section }));
            }} />
          </label>
          <label className="flex flex-col gap-1 text-[11px] text-ink-muted">
            {t.song.chord}
            <input className="ds-input !h-8 w-24 text-xs" value={value.chord} maxLength={40} onChange={(e) => {
              const chord = e.target.value;
              onChange((v) => ({ ...v, chord }));
            }} />
          </label>
          <label className="flex flex-col gap-1 text-[11px] text-ink-muted">
            {t.song.strum}
            <Select value={value.strum} onChange={(e) => {
                const strum = e.target.value as Strum;
                onChange((v) => ({ ...v, strum }));
              }} aria-label={t.song.strum}>
              <option value="">{t.song.strumNone}</option>
              <option value="down">{t.song.strumDown}</option>
              <option value="up">{t.song.strumUp}</option>
              <option value="arpeggio">{t.song.strumArpeggio}</option>
            </Select>
          </label>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full border-separate border-spacing-y-1 text-xs">
            <thead className="text-[11px] text-ink-muted">
              <tr>
                <th className="w-5" />
                <th className="w-11 text-left font-normal">{t.song.fret}</th>
                <th className="w-[92px] text-left font-normal">{t.song.grace}</th>
                <th className="text-left font-normal">{t.song.techniques}</th>
              </tr>
            </thead>
            <tbody>
              {value.notes.map((n, i) => {
                const empty = n.fret === "";
                return (
                  <tr key={i} className={i === activeString ? "[&>td]:bg-brand-tint" : ""}>
                    <td className="rounded-l-sm pr-1 font-mono text-ink-muted">
                      <button type="button" className="w-full text-left" onClick={() => onActiveString(i)} title={t.song.activeString}>
                        {STRINGS[i]}
                      </button>
                    </td>
                    <td className="pr-1.5">
                      <input
                        className={`${input} w-10`}
                        value={n.fret}
                        maxLength={2}
                        aria-label={`${STRINGS[i]} ${t.song.fret}`}
                        onFocus={() => onActiveString(i)}
                        onChange={(e) => {
                          const fret = e.target.value.trim();
                          // a new note rings on, like the converter's notes
                          setNote(i, empty && fret !== "" ? { fret, letRing: true } : { fret });
                        }}
                      />
                    </td>
                    <td className="pr-1.5">
                      <div className="flex items-center gap-1">
                        <input
                          className={`${input} w-8`}
                          value={n.grace}
                          maxLength={2}
                          disabled={empty}
                          aria-label={`${STRINGS[i]} ${t.song.grace}`}
                          onChange={(e) => setNote(i, { grace: e.target.value.trim() })}
                        />
                        <Toggle sign="/" label={t.song.tech.graceSlide} on={n.graceSlide} disabled={empty || n.grace === ""} onClick={() => setNote(i, { graceSlide: !n.graceSlide, graceHammer: false })} />
                        <Toggle sign="h" label={t.song.tech.graceHammer} on={n.graceHammer} disabled={empty || n.grace === ""} onClick={() => setNote(i, { graceHammer: !n.graceHammer, graceSlide: false })} />
                      </div>
                    </td>
                    <td>
                      <div className="flex flex-wrap gap-1">
                        {TECHNIQUES.map((k) => (
                          <Toggle
                            key={k}
                            sign={SIGN[k]}
                            label={t.song.tech[k]}
                            on={n[k]}
                            disabled={empty}
                            // hammer-on and slide both lead to the next note: one at a time
                            onClick={() => setNote(i, k === "hammer" ? { hammer: !n.hammer, slide: false } : k === "slide" ? { slide: !n.slide, hammer: false } : { [k]: !n[k] })}
                          />
                        ))}
                        <Toggle
                          sign={n.bend === 100 ? "b1" : n.bend === 50 ? "b½" : "b"}
                          label={`${t.song.tech.bend}: ${n.bend === 100 ? t.song.bendFull : n.bend === 50 ? t.song.bendHalf : t.song.bendNone}`}
                          on={n.bend > 0}
                          disabled={empty}
                          onClick={() => setNote(i, { bend: nextBend(n.bend) })}
                        />
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button type="submit" variant="primary" size="sm" disabled={saving}>
            {t.song.apply}
          </Button>
          <Button size="sm" disabled={saving} onClick={onClear}>
            {t.song.clear}
          </Button>
          <span className="mx-1 h-5 w-px bg-border" aria-hidden />
          <Button size="sm" variant="ghost" disabled={!canUndo || saving} onClick={onUndo} title={`${t.song.undo} (⌘Z)`}>
            {t.song.undo}
          </Button>
          <Button size="sm" variant="ghost" disabled={!canRedo || saving} onClick={onRedo} title={`${t.song.redo} (⇧⌘Z)`}>
            {t.song.redo}
          </Button>
          <Button size="sm" variant="ghost" aria-pressed={showKeys} onClick={onShowKeys} title="?">
            {t.song.keys}
          </Button>
          {message && <span className="text-xs text-ink-muted">{message}</span>}
        </div>
        {showKeys && (
          <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 border-t border-border pt-3 text-xs">
            {t.song.keyList.map(([k, what]) => (
              <div key={k} className="contents">
                <dt className="font-mono text-ink">{k}</dt>
                <dd className="text-ink-muted">{what}</dd>
              </div>
            ))}
          </dl>
        )}
        </div>
      </form>
    </section>
  );
}
