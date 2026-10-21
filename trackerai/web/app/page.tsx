// The front door: what each tracker is, signing up, and logging in with the account they share. The addresses come
// from the environment, so the same code serves anyone's own installation.

import { cookies } from "next/headers";
import { FrontDoor, LOCALE_COOKIE, localeFromCookie } from "@trackerai/marketing";
import { trackerUrls } from "@/lib/urls";

export const dynamic = "force-dynamic";

export default async function FrontDoorPage() {
  // English, until the visitor picks Nederlands at the bottom (proxy.ts keeps that choice in LOCALE_COOKIE).
  const locale = localeFromCookie((await cookies()).get(LOCALE_COOKIE)?.value);
  const urls = trackerUrls();
  return (
    <FrontDoor
      locale={locale}
      urls={urls}
      privacyHref={urls.wealth ? `${urls.wealth}/privacy` : urls.health ? `${urls.health}/privacy/` : undefined}
    />
  );
}
