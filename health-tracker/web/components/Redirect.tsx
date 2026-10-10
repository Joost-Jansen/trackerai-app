"use client";

// Sends a visitor from an old (Dutch) page path to its English path, keeping the query string and the anchor, so
// bookmarks and links from before the rename keep working. Used by the pages in app/(redirects); see "Old paths" in
// docs/DEVELOPMENT.md.

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function Redirect({ to }: { to: string }) {
  const router = useRouter();
  useEffect(() => router.replace(to + window.location.search + window.location.hash), [router, to]);
  return null;
}
