// trackerai.nl/admin: the admin page for every tracker. The account tools come from trackerai-api
// (/api/trackerai/admin), each tracker's own part through its hub (/api/hub/{app}); a tracker shows the same page for
// itself alone.

import type { Metadata } from "next";
import { headers } from "next/headers";
import { Admin, localeFrom } from "@trackerai/marketing";
import { trackerUrls } from "@/lib/urls";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Admin · trackerai", robots: { index: false } };

export default async function AdminPage() {
  const locale = localeFrom((await headers()).get("accept-language"));
  return <Admin locale={locale} trackers={{ health: "/api/hub/health", wealth: "/api/hub/wealth" }} urls={trackerUrls()} />;
}
