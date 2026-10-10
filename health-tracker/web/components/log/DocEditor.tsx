"use client";

// Goals or profile: read as formatted text, edit as markdown. Agents read and write the same
// document via the API, so what you record here is what the coach sees in the next session.

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Card from "@trackerai/ui/components/Card";
import { Button } from "@/components/ds";
import Markdown from "@/components/log/Markdown";
import { api, ApiError } from "@/lib/api";
import { errorText, useFormat, useT } from "@/lib/i18n";

type Doc = { key: string; body: string; updated_at: string | null; updated_by: string | null };

export default function DocEditor({ docKey }: { docKey: "profile" | "goals" }) {
  const t = useT();
  const f = useFormat();
  const title = t.log.docs[docKey];
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["doc", docKey],
    queryFn: () =>
      api.get<Doc>(`/api/docs/${docKey}`).catch((e) => {
        if (e instanceof ApiError && e.status === 404) return { key: docKey, body: "", updated_at: null, updated_by: null };
        throw e;
      }),
  });
  const [draft, setDraft] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (q.isLoading) return <p className="text-sm text-ink-muted">{t.common.loading}</p>;
  if (!q.data) return <p className="text-sm text-ink-muted">{t.log.docLoadFailed(title)}</p>;
  const doc = q.data;
  const stamp = doc.updated_at ? t.log.updated(f.dateTime(doc.updated_at), doc.updated_by ?? "") : "";

  if (draft !== null) {
    return (
      <Card
        title={t.log.editTitle(title)}
        action={
          <span className="flex gap-2">
            <Button size="sm" variant="ghost" onClick={() => setDraft(null)}>{t.common.cancel}</Button>
            <Button
              size="sm"
              variant="primary"
              onClick={async () => {
                try {
                  await api.put(`/api/docs/${docKey}`, { body: draft });
                  setDraft(null);
                  qc.invalidateQueries({ queryKey: ["doc", docKey] });
                } catch (e) {
                  setError(errorText(e, t, t.common.saveFailed));
                }
              }}
            >
              {t.common.save}
            </Button>
          </span>
        }
      >
        <div className="grid items-start gap-4 lg:grid-cols-2">
          <textarea className="ds-input h-[60vh] py-2 font-mono text-[12.5px]" value={draft} onChange={(e) => setDraft(e.target.value)} aria-label="Markdown" />
          <div className="hidden max-h-[60vh] overflow-y-auto rounded border border-border p-3 lg:block">
            <Markdown text={draft} />
          </div>
        </div>
        {error && <p className="mt-2 text-[12.5px] text-loss">{error}</p>}
      </Card>
    );
  }

  return (
    <Card action={<span className="flex items-center gap-3"><span className="text-[11.5px] text-ink-muted">{stamp}</span><Button size="sm" onClick={() => setDraft(doc.body)}>{t.common.edit}</Button></span>}>
      {doc.body ? <Markdown text={doc.body} /> : <p className="text-[13px] text-ink-muted">{t.log.empty_doc}</p>}
    </Card>
  );
}
