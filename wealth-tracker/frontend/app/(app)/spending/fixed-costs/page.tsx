// Fixed costs live under Categories; this old address sends you there.

import { redirect } from "next/navigation";

export default function FixedCostsPage() {
  redirect("/categories#fixed-costs");
}
