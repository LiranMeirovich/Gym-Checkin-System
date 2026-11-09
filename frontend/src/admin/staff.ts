// The staff list, shared by the Staff screen and the activity log's staff
// filter: one query key and one fetcher, so both screens read the same
// cached answer the same way.
import { api } from "./backend/client";

export const STAFF_KEY = ["staff"] as const;

/** The server refused the list: this role can't manage staff. */
export class Forbidden extends Error {}

export async function fetchStaff() {
  const { data, response } = await api.GET("/api/staff");
  if (data) return data.staff;
  if (response.status === 403) throw new Forbidden();
  throw new Error(`GET /api/staff failed: ${response.status}`);
}
