// Who is logged in, for every logged-in screen (decision 0019 on the
// server, moved to React by decision 0020).
//
// <RequireSession> wraps the logged-in routes. It asks GET /api/session;
// a 401 sends the browser to the lock screen, or to first-run setup on a
// fresh install. Inside it:
// - the header shows who is logged in and their role, with Lock;
// - the auto-lock timer goes to the lock screen once the role's idle time
//   has passed without an API request (only requests count as activity,
//   as on the server, which enforces the timeout either way);
// - any later 401 (the session ended or timed out) goes there too.
//
// Hiding something here is never the protection: every API route checks
// the login and permissions on the server.
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  type ReactNode,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Navigate, Outlet, useNavigate } from "react-router";
import {
  api,
  onApiResponse,
  setCsrfToken,
  type Schemas,
} from "./backend/client";

export type Session = Schemas["SessionInfo"];

export const SESSION_KEY = ["session"] as const;

type SessionState =
  | { loggedIn: true; session: Session }
  | { loggedIn: false; setupNeeded: boolean };

export const ROLE_NAMES: Record<Session["staff"]["role"], string> = {
  manager: "מנהל/ת",
  instructor: "מדריך/ה",
};

async function fetchSession(): Promise<SessionState> {
  const { data, error, response } = await api.GET("/api/session");
  if (data) {
    // After a reload the in-memory token is gone; this brings it back.
    setCsrfToken(data.csrf_token);
    return { loggedIn: true, session: data };
  }
  if (response.status === 401 && error) {
    return { loggedIn: false, setupNeeded: error.setup_needed };
  }
  throw new Error(`GET /api/session failed: ${response.status}`);
}

/** Call with the session from a successful login or setup. */
export function useStartSession(): (session: Session) => void {
  const queryClient = useQueryClient();
  return useCallback(
    (session: Session) => {
      setCsrfToken(session.csrf_token);
      const state: SessionState = { loggedIn: true, session };
      queryClient.setQueryData(SESSION_KEY, state);
    },
    [queryClient],
  );
}

/** Forget the session on this page. The server ends it (Lock, or the lock
 * screen loading); this just drops what React knew. */
export function useForgetSession(): () => void {
  const queryClient = useQueryClient();
  return useCallback(() => {
    setCsrfToken(null);
    queryClient.removeQueries({ queryKey: SESSION_KEY });
  }, [queryClient]);
}

const SessionContext = createContext<Session | null>(null);

/** The logged-in session; only inside <RequireSession>. */
export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession() outside <RequireSession>");
  return session;
}

export function RequireSession() {
  const { data, isPending, isError } = useQuery({
    queryKey: SESSION_KEY,
    queryFn: fetchSession,
    // Kept until Lock, a 401 or a reload; the server is the judge anyway.
    staleTime: Infinity,
  });

  if (isPending) return null;
  if (isError) return <p role="alert">אין חיבור לשרת. נסו לרענן את הדף.</p>;
  if (!data.loggedIn) {
    return <Navigate to={data.setupNeeded ? "/setup" : "/login"} replace />;
  }
  return (
    <LoggedIn session={data.session}>
      <Outlet />
    </LoggedIn>
  );
}

function LoggedIn({
  session,
  children,
}: {
  session: Session;
  children: ReactNode;
}) {
  const navigate = useNavigate();
  const forgetSession = useForgetSession();

  useEffect(() => {
    const lockAfterMs = session.lock_after_seconds * 1000;
    let timer = setTimeout(goToLockScreen, lockAfterMs);
    function goToLockScreen() {
      // The lock screen ends the session on the server as it loads.
      navigate("/login", { replace: true });
    }
    const unsubscribe = onApiResponse((_request, response) => {
      if (response.status === 401) {
        goToLockScreen();
        return;
      }
      clearTimeout(timer);
      timer = setTimeout(goToLockScreen, lockAfterMs);
    });
    return () => {
      clearTimeout(timer);
      unsubscribe();
    };
  }, [session.lock_after_seconds, navigate]);

  async function lock() {
    await api.POST("/api/lock");
    forgetSession();
    navigate("/login", { replace: true });
  }

  return (
    <SessionContext.Provider value={session}>
      <header>
        <span>
          {session.staff.display_name} · {ROLE_NAMES[session.staff.role]}
        </span>{" "}
        <button type="button" onClick={lock}>
          נעילה
        </button>
      </header>
      <main>{children}</main>
    </SessionContext.Provider>
  );
}
