function required(name: string, value: string | undefined): string {
  if (!value) throw new Error(`Missing ${name}. Copy .env.example to .env at the repo root.`);
  return value;
}

export const config = {
  oidcAuthority: required("VITE_OIDC_AUTHORITY", import.meta.env.VITE_OIDC_AUTHORITY),
  oidcClientId: required("VITE_OIDC_CLIENT_ID", import.meta.env.VITE_OIDC_CLIENT_ID),
};
