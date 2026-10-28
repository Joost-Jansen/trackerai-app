"use client";

// An uploaded PDF (a tab, a chord sheet, sheet music): read it in the page, keep its status and tags.

import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { DownloadIcon } from "@trackerai/ui/icons";
import SongChips from "@/components/SongChips";
import TopbarTitle from "@/components/TopbarTitle";
import { api, type Song } from "@/lib/api";
import { useT } from "@/lib/i18n";

function Pdf({ id }: { id: string }) {
  const t = useT();
  const qc = useQueryClient();
  const router = useRouter();
  const songs = useQuery({ queryKey: ["songs"], queryFn: () => api.get<Song[]>("/api/songs") });
  const item = songs.data?.find((s) => s.video === id);
  const src = `/api/songs/${encodeURIComponent(id)}/pdf`;
  const remove = async () => {
    if (!window.confirm(t.watch.removeConfirm(item?.title ?? id))) return;
    await api.del(`/api/songs/${id}`);
    await qc.invalidateQueries({ queryKey: ["songs"] });
    router.push("/library/");
  };
  return (
    <div className="flex flex-col gap-3">
      <TopbarTitle
        title={item?.title ?? "…"}
        meta={item?.artist}
        chips={item && <SongChips song={item} />}
        back="/library/"
        backLabel={t.song.back}
        actions={
          <a className="ds-btn ds-btn--ghost ds-btn--sm !px-1.5" href={src} target="_blank" rel="noreferrer" title={t.watch.openPdf} aria-label={t.watch.openPdf}>
            <DownloadIcon className="h-[15px] w-[15px]" />
          </a>
        }
      />
      <div className="flex flex-wrap items-center gap-3">
        <span className="flex-1" />
        <button type="button" className="text-xs text-ink-muted hover:underline" onClick={() => void remove()}>
          {t.watch.remove}
        </button>
      </div>
      <iframe src={src} title={item?.title ?? "PDF"} className="h-[calc(100dvh-170px)] min-h-[420px] w-full rounded border border-border bg-surface" />
    </div>
  );
}

function PdfPage() {
  const id = useSearchParams().get("id");
  return id ? <Pdf key={id} id={id} /> : null;
}

export default function Page() {
  return (
    <Suspense>
      <PdfPage />
    </Suspense>
  );
}
