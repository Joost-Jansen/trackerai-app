"use client";

// The shared feedback dialog (@trackerai/ui), posting to this app's API with which app it came from.

import Dialog from "@trackerai/ui/components/FeedbackDialog";
import { api, ApiError } from "@/lib/api";

export default function FeedbackDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      send={(payload) => api.post("/api/feedback", { ...payload, app: "money" })}
      errorText={(e) => (e instanceof ApiError ? e.message : undefined)}
    />
  );
}
