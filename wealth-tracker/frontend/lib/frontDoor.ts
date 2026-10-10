// The front door of this installation (trackerai.nl), when it has one: the API says so (front_door_url in
// /api/auth/registration-status). The admin links then go to its /admin, the page for every tracker; without one, to
// this app's own admin page (the same page, for this tracker only).

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

type Status = { front_door_url?: string | null; tracker_urls?: Record<string, string | null> };

function useStatus(enabled: boolean) {
  return useQuery({
    queryKey: ["registration-status"],
    queryFn: () => api.get<Status>("/api/auth/registration-status"),
    staleTime: Infinity,
    retry: false,
    enabled,
  }).data;
}

const clean = (url: unknown) => (typeof url === "string" && url ? url.replace(/\/+$/, "") : null);

export function useFrontDoor(enabled = true): string | null {
  return clean(useStatus(enabled)?.front_door_url);
}

/** Where the other tracker lives (the link next to "Log out"), or null when this installation has only this one. */
export function useTrackerUrl(app: "health" | "wealth", enabled = true): string | null {
  return clean(useStatus(enabled)?.tracker_urls?.[app]);
}

/** Where the admin link goes: the front door's page when there is one, this app's own otherwise. */
export const adminHref = (frontDoor: string | null) => (frontDoor ? `${frontDoor}/admin` : "/admin");
