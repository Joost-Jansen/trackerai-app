"use client";

// Your own notes on the library page: one free text (songs you can play that have no video here, what to learn
// next), saved while you type (GET/PUT /api/notes).

import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Card from "@trackerai/ui/components/Card";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";

const SAVE_AFTER = 800; // ms after the last key

export default function NotesCard() {
  const t = useT();
  const qc = useQueryClient();
  const notes = useQuery({ queryKey: ["notes"], queryFn: () => api.get<{ text: string }>("/api/notes") });
  const [text, setText] = useState<string | null>(null); // null until loaded, then what you typed
  const [state, setState] = useState<"saved" | "saving" | "failed">("saved");
  const saved = useRef<string | null>(null); // the text the server has
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (notes.data && text === null) {
      setText(notes.data.text);
      saved.current = notes.data.text;
    }
  }, [notes.data, text]);

  const save = (value: string) => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    if (value === saved.current) return;
    setState("saving");
    api
      .put<{ text: string }>("/api/notes", { text: value })
      .then((r) => {
        saved.current = r.text;
        qc.setQueryData(["notes"], r);
        setState((s) => (s === "saving" ? "saved" : s));
      })
      .catch(() => setState("failed"));
  };
  // what is still waiting goes out when you leave the page
  const latest = useRef(text);
  latest.current = text;
  useEffect(
    () => () => {
      if (timer.current && latest.current !== null) save(latest.current);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  if (text === null) return null;
  const rows = Math.min(30, Math.max(6, text.split("\n").length + 1));
  return (
    <Card
      title={t.library.notes.title}
      action={
        <span className={`text-xs ${state === "failed" ? "text-neg" : "text-ink-muted"}`} aria-live="polite">
          {state === "failed"
            ? t.library.notes.failed
            : state === "saving" || text !== saved.current
              ? t.library.notes.saving
              : t.library.notes.saved}
        </span>
      }
    >
      <p className="mb-2 text-xs text-ink-muted">{t.library.notes.hint}</p>
      <textarea
        // ds-input is a one-line field (a fixed height): here the rows decide, growing with the text
        className="ds-input !h-auto w-full resize-y py-2 text-sm leading-relaxed"
        aria-label={t.library.notes.title}
        placeholder={t.library.notes.placeholder}
        rows={rows}
        maxLength={20000}
        value={text}
        onChange={(e) => {
          const v = e.target.value;
          setText(v);
          if (timer.current) clearTimeout(timer.current);
          timer.current = setTimeout(() => save(v), SAVE_AFTER);
        }}
        onBlur={() => save(text)}
      />
    </Card>
  );
}
