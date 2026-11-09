// A query that refreshes itself on a timer: the dashboard's lists, the
// phone list while a link code shows.
//
// Only the timed refreshes are background refreshes (`BACKGROUND_REFRESH`):
// the server doesn't count them as activity, and neither does the
// auto-lock timer in session.tsx, so a screen left refreshing still locks
// on time. Every other fetch of the same query counts as activity, because
// a person caused it: the first load, coming back to the screen, returning
// to the window, a reload after a failed save.
//
// TanStack Query's own `refetchInterval` can't tell its timed fetches from
// the rest, so the timer is here: it marks the query, then refetches it,
// and the query function sends the header only when it finds the mark.
import { useEffect } from "react";
import {
  hashKey,
  useQuery,
  useQueryClient,
  type QueryKey,
} from "@tanstack/react-query";
import { BACKGROUND_REFRESH } from "./backend/client";

// Queries whose next fetch is a timed refresh, by query hash.
const timedFetch = new Set<string>();

export function usePolledQuery<T>({
  queryKey,
  fetch,
  everyMs,
  until,
}: {
  queryKey: QueryKey;
  /** Fetches the data, sending `headers` with its GET. */
  fetch: (headers: Record<string, string>) => Promise<T>;
  /** How often to refresh; `false` doesn't. A function decides from the
   * data shown now. */
  everyMs: number | false | ((data: T | undefined) => number | false);
  /** Stop refreshing at this time (milliseconds since the epoch). */
  until?: number;
}) {
  const client = useQueryClient();
  const hash = hashKey(queryKey);
  const query = useQuery({
    queryKey,
    queryFn: () => fetch(timedFetch.delete(hash) ? BACKGROUND_REFRESH : {}),
  });
  const interval =
    typeof everyMs === "function" ? everyMs(query.data) : everyMs;

  useEffect(() => {
    if (interval === false) return;
    const timer = setInterval(() => {
      // Hidden: wait. Coming back refetches anyway, as activity.
      if (document.hidden) return;
      if (until !== undefined && Date.now() >= until) {
        clearInterval(timer);
        return;
      }
      timedFetch.add(hash);
      void client
        .refetchQueries({ predicate: (found) => found.queryHash === hash })
        .finally(() => timedFetch.delete(hash));
    }, interval);
    return () => clearInterval(timer);
  }, [client, hash, interval, until]);

  return query;
}
