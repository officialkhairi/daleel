import "./index.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { ErrorBoundary } from "./ErrorBoundary";
import i18n from "./i18n";
import { config } from "./config";
import { AuthProvider } from "./features/auth/AuthProvider";
import { createUserManager } from "./features/auth/oidc";
import { ApiError } from "./lib/api";
import { startTracing } from "./lib/tracing";

void startTracing();

const manager = createUserManager(config.oidcAuthority, config.oidcClientId);
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failures, error) => failures < 2 && (!(error instanceof ApiError) || error.retryable),
    },
  },
});

const root = document.getElementById("root");
if (!root) throw new Error("#root missing from index.html");

createRoot(root).render(
  <StrictMode>
    <AuthProvider manager={manager}>
      <QueryClientProvider client={queryClient}>
        <ErrorBoundary
          fallback={() => (
            <main className="mx-auto max-w-xl p-8">
              <h1 className="text-xl font-semibold text-ink">{i18n.t("errors.crashTitle")}</h1>
              <p className="mt-2 text-muted">{i18n.t("errors.crashBody")}</p>
              <button
                type="button"
                onClick={() => {
                  window.location.reload();
                }}
                className="mt-4 rounded-md bg-brand px-4 py-2 font-medium text-brand-ink"
              >
                {i18n.t("errors.reload")}
              </button>
            </main>
          )}
        >
          <App />
        </ErrorBoundary>
      </QueryClientProvider>
    </AuthProvider>
  </StrictMode>,
);
