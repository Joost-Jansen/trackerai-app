"use client";

// To label — one queue. At the top how far you are and what Claude can do for
// you (with its settings); below it everything that needs a decision from you,
// largest amounts first, with the same choices everywhere.

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { LabelStatus, type AiStatus } from "@/components/money/labelling/ClaudeStatus";
import Queue, { useDecisions, waiting, type Kind, type QueueData } from "@/components/money/labelling/Queue";
import type { Category } from "@/lib/money";

export default function UnlabelledPage() {
  const qc = useQueryClient();
  const refresh = () => {
    qc.invalidateQueries();
  };
  const decisions = useDecisions(refresh);
  const [filter, setFilter] = useState<Kind | "everything">("everything");
  // From Claude's summary: show that kind and scroll to it.
  const show = (kind: Kind) => {
    setFilter(kind);
    document.getElementById("queue")?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  const categories = useQuery({
    queryKey: ["categories"],
    queryFn: () => api.get<{ categories: Category[] }>("/api/categories"),
  });
  const queue = useQuery({
    queryKey: ["labelling", "queue"],
    queryFn: () => api.get<QueueData>("/api/labelling/queue"),
  });
  const ai = useQuery({
    queryKey: ["categories", "ai"],
    queryFn: () => api.get<AiStatus>("/api/categories/ai"),
  });

  if (queue.isLoading || categories.isLoading || !queue.data) {
    return <div className="h-72 animate-pulse rounded" style={{ background: "var(--surface-inset)" }} />;
  }
  const data = queue.data;
  return (
    <div className="flex min-w-0 flex-col gap-6">
      <LabelStatus
        coverage={data.coverage}
        waiting={waiting(data, decisions.away)}
        most_recent={data.most_recent_checked}
        ai={ai.data}
        onDone={refresh}
        onShow={show}
      />
      <Queue
        data={data}
        categories={categories.data?.categories ?? []}
        decisions={decisions}
        onDone={refresh}
        filter={filter}
        onFilter={setFilter}
      />
    </div>
  );
}
