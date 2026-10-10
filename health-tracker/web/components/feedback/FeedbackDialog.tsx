"use client";

// The shared feedback dialog (@trackerai/ui), posting to this app's API.

import Dialog from "@trackerai/ui/components/FeedbackDialog";
import { api } from "@/lib/api";
import { errorText, useT } from "@/lib/i18n";

export default function FeedbackDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useT();
  return (
    <Dialog
      open={open}
      onClose={onClose}
      send={(payload) => api.post("/api/feedback", payload)}
      errorText={(e) => errorText(e, t, t.feedback.failed)}
    />
  );
}
