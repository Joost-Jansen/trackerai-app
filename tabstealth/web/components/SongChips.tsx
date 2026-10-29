"use client";

// A song's status, tags and favourite as small chips next to its name (PATCH /api/songs/{id}). Click the status to
// pick another, a tag to rename it (empty removes it), "+ tag" to add one, the heart to favourite.

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { HeartIcon } from "@trackerai/ui/icons";
import { api, STATUSES, type Song, type Status } from "@/lib/api";
import { useT } from "@/lib/i18n";

const chip = "inline-flex h-5 items-center rounded-full border px-2 text-[11px] leading-none transition-colors";
const TONE: Record<Status, string> = {
  new: "border-border text-ink-muted",
  checking: "border-warn/50 text-warn",
  learning: "border-brand/50 bg-brand-tint text-brand",
  mastered: "border-pos/50 text-pos",
};

/** A tag being edited in place: Enter or leaving the field saves, Escape cancels. */
function TagInput({ initial, onDone }: { initial: string; onDone: (value: string | null) => void }) {
  const [v, setV] = useState(initial);
  const done = useRef(false);
  const finish = (value: string | null) => {
    if (done.current) return;
    done.current = true;
    onDone(value);
  };
  return (
    <input
      autoFocus
      value={v}
      size={Math.max(4, v.length + 1)}
      onChange={(e) => setV(e.target.value)}
      onBlur={() => finish(v)}
      onKeyDown={(e) => {
        if (e.key === "Enter") finish(v);
        if (e.key === "Escape") finish(null);
        e.stopPropagation(); // typing a tag is not a shortcut
      }}
      className={`${chip} border-brand bg-surface text-ink outline-none`}
    />
  );
}

export default function SongChips({ song }: { song: Song }) {
  const t = useT();
  const qc = useQueryClient();
  const [menu, setMenu] = useState(false);
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const box = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!menu) return;
    const away = (e: MouseEvent) => box.current && !box.current.contains(e.target as Node) && setMenu(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setMenu(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [menu]);

  const patch = async (body: Partial<{ status: Status; tags: string[]; favourite: boolean }>) => {
    // show it at once, then save
    qc.setQueryData<Song[]>(["songs"], (list) => list?.map((s) => (s.video === song.video ? { ...s, ...body } : s)));
    await api.patch(`/api/songs/${song.video}`, body);
    void qc.invalidateQueries({ queryKey: ["songs"] });
  };
  const setTag = (i: number | "new", value: string | null) => {
    setEditing(null);
    if (value === null) return;
    const tags = [...song.tags];
    const v = value.trim().replace(/^#/, "").toLowerCase();
    if (i === "new") {
      if (v && !tags.includes(v)) void patch({ tags: [...tags, v] });
    } else if (v !== tags[i]) {
      if (v) tags[i] = v;
      else tags.splice(i, 1);
      void patch({ tags });
    }
  };

  const heart = (
    <button
      type="button"
      aria-pressed={song.favourite}
      aria-label={t.library.favourite}
      title={t.library.favourite}
      onClick={() => void patch({ favourite: !song.favourite })}
      className={`inline-flex h-5 w-5 flex-none items-center justify-center ${song.favourite ? "text-brand" : "text-ink-muted opacity-60 hover:opacity-100"}`}
    >
      <HeartIcon className="h-3.5 w-3.5" fill={song.favourite ? "currentColor" : "none"} />
    </button>
  );

  return (
    <span className="inline-flex max-w-full flex-wrap items-center gap-1 align-middle">
      {heart}
      <span ref={box} className="relative">
        <button
          type="button"
          className={`${chip} ${TONE[song.status]}`}
          aria-haspopup="menu"
          aria-expanded={menu}
          title={t.library.statusLabel}
          onClick={() => setMenu((v) => !v)}
        >
          {t.library.statuses[song.status]}
        </button>
        {menu && (
          <span
            role="menu"
            className="absolute left-0 top-6 z-50 flex min-w-[140px] flex-col rounded-md border border-border bg-surface p-1 shadow-lg"
          >
            {STATUSES.map((s) => (
              <button
                key={s}
                type="button"
                role="menuitemradio"
                aria-checked={s === song.status}
                onClick={() => {
                  setMenu(false);
                  if (s !== song.status) void patch({ status: s });
                }}
                className={`rounded-sm px-2 py-1.5 text-left text-xs hover:bg-surface-2 ${s === song.status ? "font-semibold text-brand" : ""}`}
              >
                {t.library.statuses[s]}
              </button>
            ))}
          </span>
        )}
      </span>
      {song.tags.map((tag, i) =>
        editing === i ? (
          <TagInput key={tag} initial={tag} onDone={(v) => setTag(i, v)} />
        ) : (
          <button
            key={tag}
            type="button"
            className={`${chip} border-border text-ink-muted hover:border-border-strong`}
            title={t.library.editTag}
            onClick={() => setEditing(i)}
          >
            #{tag}
          </button>
        ),
      )}
      {editing === "new" ? (
        <TagInput initial="" onDone={(v) => setTag("new", v)} />
      ) : (
        <button
          type="button"
          className={`${chip} border-dashed border-border text-ink-muted hover:border-border-strong`}
          onClick={() => setEditing("new")}
        >
          + {t.library.tag}
        </button>
      )}
    </span>
  );
}
