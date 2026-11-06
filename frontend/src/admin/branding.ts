// The gym's name and whether there is a logo (GET /api/branding), for the
// header, the lock screen and setup. Fetched once per page load.
import { useQuery } from "@tanstack/react-query";
import type { Branding } from "../shared/Brand";
import { api } from "./backend/client";

// First-run setup saves the gym name, so it refreshes this.
export const BRANDING_KEY = ["branding"] as const;

async function fetchBranding(): Promise<Branding> {
  const { data, response } = await api.GET("/api/branding");
  if (!data) throw new Error(`GET /api/branding failed: ${response.status}`);
  return data;
}

/** Undefined while loading or if it failed: the brand then stays empty,
 * and the screen's own request shows any connection error. */
export function useBranding(): Branding | undefined {
  return useQuery({
    queryKey: BRANDING_KEY,
    queryFn: fetchBranding,
    staleTime: Infinity,
  }).data;
}
