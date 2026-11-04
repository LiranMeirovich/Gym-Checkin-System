// The one way the customer app talks to its backend (decision 0020).
//
// `api` is typed from schema.d.ts, generated from the public app's OpenAPI
// spec (`npm run api:types`), so it only knows the public routes.
//
// The customer's login is the HttpOnly `gym_device` cookie, which the
// browser sends on its own and this code can never read or store. There's
// no CSRF token here: the public app refuses writes that don't come from
// its own origin.
import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];

// Same origin: FastAPI serves this app and its API (Vite proxies /api in
// development), so paths are relative and cookies go along by default.
export const api = createClient<paths>({ baseUrl: "" });
