import { redirect } from "next/navigation";
import { APP } from "@/lib/app";

export default function RootPage() {
  redirect(APP.home);
}
