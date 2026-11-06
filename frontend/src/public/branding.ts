// The customer app's call for the gym's name and logo, for the top of
// every phone page (the hook itself is src/shared/useBranding.ts).
import type { Branding } from "../shared/Brand";
import { useBranding as useSharedBranding } from "../shared/useBranding";
import { api } from "./backend/client";

async function fetchBranding(): Promise<Branding> {
  const { data, response } = await api.GET("/api/branding");
  if (!data) throw new Error(`GET /api/branding failed: ${response.status}`);
  return data;
}

export function useBranding(): Branding | undefined {
  return useSharedBranding(fetchBranding);
}
