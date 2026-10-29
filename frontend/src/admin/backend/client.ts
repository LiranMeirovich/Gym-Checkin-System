// The one way the admin app talks to its backend (decision 0020).
//
// `api` is typed from schema.d.ts, which is generated from the backend's
// OpenAPI spec (`npm run api:types`): every path, request body and
// response is checked at compile time, so a backend change that breaks a
// screen fails the build instead of the front desk.
//
// The staff login itself is the HttpOnly `gym_staff` cookie, which the
// browser sends on its own and this code can never read. What it does
// hold is the session's CSRF token, in this module's memory only (never
// localStorage or the like): it's gone on a reload and fetched again from
// GET /api/session.
import createClient, { type Middleware } from "openapi-fetch";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

let csrfToken: string | null = null;

/** Set after login or GET /api/session; cleared on lock. */
export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

type ResponseListener = (request: Request, response: Response) => void;
const responseListeners = new Set<ResponseListener>();

/** Called after every API response (the auto-lock timer, a 401 sending
 * the page to the lock screen). Returns a function that unsubscribes. */
export function onApiResponse(listener: ResponseListener): () => void {
  responseListeners.add(listener);
  return () => responseListeners.delete(listener);
}

const sessionMiddleware: Middleware = {
  onRequest({ request }) {
    if (csrfToken && UNSAFE_METHODS.has(request.method)) {
      request.headers.set("X-CSRF-Token", csrfToken);
    }
    return request;
  },
  onResponse({ request, response }) {
    for (const listener of responseListeners) listener(request, response);
    return response;
  },
};

// Same origin: FastAPI serves this app and its API (Vite proxies /api in
// development), so paths are relative and cookies go along by default.
export const api = createClient<paths>({ baseUrl: "" });
api.use(sessionMiddleware);
