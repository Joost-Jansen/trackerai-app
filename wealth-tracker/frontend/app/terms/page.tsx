// Terms. Public, like the privacy statement: a bank connection can ask for both
// addresses. Short, and without personal data — see privacy/page.tsx.

import type { Metadata } from "next";
import { APP } from "@/lib/app";
import TermsPageContent from "./content";

export const metadata: Metadata = { title: `Terms · ${APP.name}` };

export default function TermsPage() {
  return <TermsPageContent />;
}
