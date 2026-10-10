"use client";

// Admin: the shared admin page (packages/marketing, Admin.tsx), for this tracker only. The same page as
// trackerai.nl/admin, so a wealth-tracker without the front door has one too. When the front door is there, the
// admin links point to it (lib/frontDoor.ts) and this page links to it quietly.
//
// Hiding the tab is not security: every admin route checks again whether you are an admin.

import { Admin } from "@trackerai/marketing";
import "@trackerai/marketing/marketing.css";
import { locale } from "@/lib/i18n";
import { useFrontDoor } from "@/lib/frontDoor";

export default function AdminPage() {
  const frontDoor = useFrontDoor();
  return <Admin locale={locale} trackers={{ wealth: "/api" }} inApp frontDoor={frontDoor} registerPath="/register" />;
}
