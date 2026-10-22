import type { User, UserManager } from "oidc-client-ts";
import { createContext, use, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { CALLBACK_PATH } from "./oidc";

export type AuthState =
  | { status: "loading" }
  | { status: "signedOut"; error?: "signInFailed" }
  | { status: "signedIn"; user: User };

interface AuthContextValue {
  state: AuthState;
  signIn: () => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/** The subset of oidc-client-ts's UserManager the app uses; lets tests pass a fake. */
export type AuthManager = Pick<
  UserManager,
  "getUser" | "signinRedirect" | "signinRedirectCallback" | "signoutRedirect" | "removeUser" | "events"
>;

export function AuthProvider({ manager, children }: { manager: AuthManager; children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: "loading" });
  // The redirect callback consumes one-time state, so it must run once even under StrictMode.
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    const isCallback = window.location.pathname === CALLBACK_PATH;
    const load = isCallback ? manager.signinRedirectCallback() : manager.getUser();
    load
      .then((user) => {
        setState(user && !user.expired ? { status: "signedIn", user } : { status: "signedOut" });
      })
      .catch(() => {
        setState({ status: "signedOut", error: "signInFailed" });
      })
      .finally(() => {
        if (isCallback) window.history.replaceState(null, "", "/");
      });
  }, [manager]);

  useEffect(() => {
    const onLoaded = (user: User) => {
      setState({ status: "signedIn", user });
    };
    const onGone = () => {
      setState({ status: "signedOut" });
    };
    const onRenewFailed = () => {
      void manager.removeUser();
    };
    manager.events.addUserLoaded(onLoaded);
    manager.events.addUserUnloaded(onGone);
    manager.events.addAccessTokenExpired(onGone);
    manager.events.addSilentRenewError(onRenewFailed);
    return () => {
      manager.events.removeUserLoaded(onLoaded);
      manager.events.removeUserUnloaded(onGone);
      manager.events.removeAccessTokenExpired(onGone);
      manager.events.removeSilentRenewError(onRenewFailed);
    };
  }, [manager]);

  const value = useMemo<AuthContextValue>(
    () => ({
      state,
      signIn: () => manager.signinRedirect(),
      signOut: () => manager.signoutRedirect(),
    }),
    [manager, state],
  );

  return <AuthContext value={value}>{children}</AuthContext>;
}

export function useAuth(): AuthContextValue {
  const ctx = use(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

/** The current access token. Only call below a signed-in boundary. */
export function useAccessToken(): string {
  const { state } = useAuth();
  if (state.status !== "signedIn") throw new Error("useAccessToken requires a signed-in user");
  return state.user.access_token;
}
