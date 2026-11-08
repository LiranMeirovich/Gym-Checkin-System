// "No connection to the server", the same wording on every screen.

/** For a request the person sent (a save, a login): try it again. */
export const NO_CONNECTION_TRY_AGAIN = "אין חיבור לשרת. נסו שוב.";

/** For a page that couldn't load: reload it. */
export const NO_CONNECTION_RELOAD = "אין חיבור לשרת. נסו לרענן את הדף.";

/** Shown in place of a page or section that couldn't load. */
export function NoConnection() {
  return <p role="alert">{NO_CONNECTION_RELOAD}</p>;
}
