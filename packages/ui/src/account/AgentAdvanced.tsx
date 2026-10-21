"use client";
import { useTr } from "@trackerai/ui/i18n";
import type { ReactNode } from "react";
export default function AgentAdvanced({ children, collapsed = true }: { children: ReactNode; collapsed?: boolean }) {
  const tr = useTr();
  if (!collapsed) return <>{children}</>;
  return (
    <details className="flex flex-col gap-4">
      <summary className="cursor-pointer py-2 text-sm font-medium">{tr("Advanced setup")}</summary>
      {children}
    </details>
  );
}
