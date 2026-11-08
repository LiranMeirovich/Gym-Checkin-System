// The gym's name and whether there is a logo (GET /api/branding), for both
// apps. Shared code imports neither app, so each passes in its own call
// (src/admin/branding.ts, src/public/branding.ts).
import { useQuery } from "@tanstack/react-query";
import type { Branding } from "./Brand";

// First-run setup saves the gym name, so it refreshes this.
export const BRANDING_KEY = ["branding"] as const;

/** Undefined while loading or if it failed: the brand then stays empty,
 * and the screen's own request shows any connection error. Fetched once
 * per page load; unlike the apps' other queries it retries, since it only
 * reads and a phone on a weak signal would otherwise keep an empty top
 * bar until a reload. */
export function useBranding(
  fetchBranding: () => Promise<Branding>,
): Branding | undefined {
  return useQuery({
    queryKey: BRANDING_KEY,
    queryFn: fetchBranding,
    staleTime: Infinity,
    retry: 2,
  }).data;
}
