// Dates as the customer pages and the shared health form show them.

/** An ISO date from the API ("2026-11-04") as "04/11/2026". */
export function formatDay(iso: string): string {
  const [year, month, day] = iso.slice(0, 10).split("-");
  return `${day}/${month}/${year}`;
}
