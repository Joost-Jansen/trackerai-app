"use client";

// Since the Help page, the money explanation lives under Help → Money. This
// address keeps working for old links and bookmarks, with the chapter
// (#labelling, #balances) included.

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function ExplanationRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace(`/help/money${window.location.hash}`);
  }, [router]);
  return null;
}
