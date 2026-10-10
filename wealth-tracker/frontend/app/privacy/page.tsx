// Privacy statement. Public, outside the (app) group: a bank connection asks for
// an address anyone can open, also without an account.
//
// No name or address of a person: the same code runs for everyone who hosts an
// installation, so the text speaks of "the administrator". Everything here must
// match what the code does — whoever changes which data the app fetches or
// passes on updates this page along with it.

import type { Metadata } from "next";
import { APP } from "@/lib/app";
import PrivacyPageContent from "./content";

export const metadata: Metadata = { title: `Privacy · ${APP.name}` };

export default function PrivacyPage() {
  return <PrivacyPageContent />;
}
