"use client";

// A song's own bookkeeping on its page: status, favourite and tags (PATCH /api/songs/{id}).

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Select } from "@trackerai/ui/ds/Field";
import { HeartIcon } from "@trackerai/ui/icons";
import { api, STATUSES, type Song, type Status } from "@/lib/api";
import { useT } from "@/lib/i18n";

export default function SongMeta({ song }: { song: Song }) {
  const t = useT();
  const qc = useQueryClient();
  const [tags, setTags] = useState(song.tags.join(", "));
  useEffect(() => setTags(song.tags.join(", ")), [song.tags]);
  const patch = async (body: Partial<{ status: Status; tags: string[]; favourite: boolean }>) => {
    await api.patch(`/api/songs/${song.video}`, body);
    void qc.invalidateQueries({ queryKey: ["songs"] });
  };
  const saveTags = () => {
    const list = tags.split(",").map((x) => x.trim()).filter(Boolean);
    if (list.join(",") !== song.tags.join(",")) void patch({ tags: list });
  };
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <Select value={song.status} onChange={(e) => void patch({ status: e.target.value as Status })} aria-label={t.library.statusLabel}>
        {STATUSES.map((s) => (
          <option key={s} value={s}>
            {t.library.statuses[s]}
          </option>
        ))}
      </Select>
      <button
        type="button"
        aria-pressed={song.favourite}
        aria-label={t.library.favourite}
        title={t.library.favourite}
        onClick={() => void patch({ favourite: !song.favourite })}
        className={`ds-btn ds-btn--ghost ds-btn--sm !px-1.5 ${song.favourite ? "text-brand" : "text-ink-muted"}`}
      >
        <HeartIcon className="h-4 w-4" fill={song.favourite ? "currentColor" : "none"} />
      </button>
      <input
        className="ds-input !h-8 min-w-0 flex-1 text-xs"
        value={tags}
        placeholder={t.library.tagsPlaceholder}
        aria-label={t.library.tags}
        onChange={(e) => setTags(e.target.value)}
        onBlur={saveTags}
        onKeyDown={(e) => e.key === "Enter" && (e.currentTarget as HTMLInputElement).blur()}
      />
    </div>
  );
}
