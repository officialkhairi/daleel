import { UserManager, WebStorageStateStore } from "oidc-client-ts";

export const CALLBACK_PATH = "/callback";

/** Authorization Code + PKCE against Keycloak. Tokens live in sessionStorage (per tab), never localStorage. */
export function createUserManager(authority: string, clientId: string): UserManager {
  const origin = window.location.origin;
  return new UserManager({
    authority,
    client_id: clientId,
    redirect_uri: `${origin}${CALLBACK_PATH}`,
    post_logout_redirect_uri: `${origin}/`,
    response_type: "code",
    scope: "openid profile email",
    automaticSilentRenew: true,
    userStore: new WebStorageStateStore({ store: window.sessionStorage }),
  });
}
