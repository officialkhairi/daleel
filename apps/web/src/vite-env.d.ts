/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_OIDC_AUTHORITY?: string;
  readonly VITE_OIDC_CLIENT_ID?: string;
  readonly VITE_OTEL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
