// The gym's name and whether there is a logo (GET /api/branding), for the
// top of every phone page. Fetched once per page load.
import { useQuery } from "@tanstack/react-query";
import type { Branding } from "../shared/Brand";
import { api } from "./backend/client";

async function fetchBranding(): Promise<Branding> {
  const { data, response } = await api.GET("/api/branding");
  if (!data) throw new Error(`GET /api/branding failed: ${response.status}`);
  return data;
}

/** Undefined while loading or if it failed: the brand then stays empty,
 * and the page's own request shows any connection error. */
export function useBranding(): Branding | undefined {
  return useQuery({
    queryKey: ["branding"],
    queryFn: fetchBranding,
    staleTime: Infinity,
  }).data;
}
