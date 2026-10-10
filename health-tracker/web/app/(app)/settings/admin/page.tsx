"use client";

// Admin (admins only): the shared admin page (packages/marketing, Admin.tsx), for health-tracker only. The same page
// as trackerai.nl/admin, so a health-tracker without the front door has one too. When the front door is there, the
// admin tab points to it (lib/frontDoor.ts) and this page links to it quietly.

import { Admin } from "@trackerai/marketing";
import "@trackerai/marketing/marketing.css";
import { useLocale } from "@/lib/i18n";
import { useFrontDoor } from "@/lib/frontDoor";

export default function AdminPage() {
  const { locale } = useLocale();
  const frontDoor = useFrontDoor();
  return <Admin locale={locale} trackers={{ health: "/api" }} inApp frontDoor={frontDoor} registerPath="/register/" />;
}
