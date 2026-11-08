// Dates and times as the customer pages show them. Plan names, prices and
// months are shared with the admin app (src/shared/plans.ts).

/** "2026-12" → "31/12/2026": the month's last day. */
export function lastDayOf(month: string): string {
  const year = Number(month.slice(0, 4));
  const number = Number(month.slice(5, 7));
  // Day 0 of the next month is this month's last day.
  const day = new Date(Date.UTC(year, number, 0)).getUTCDate();
  return `${day}/${String(number).padStart(2, "0")}/${year}`;
}

/** A timestamp from the API as the time in Israel, "14:05". */
export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("he-IL", {
    timeZone: "Asia/Jerusalem",
    hour: "2-digit",
    minute: "2-digit",
  });
}
