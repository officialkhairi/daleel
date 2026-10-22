import "./index.css";
import "./i18n";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { config } from "./config";
import { AuthProvider } from "./features/auth/AuthProvider";
import { createUserManager } from "./features/auth/oidc";
import { ApiError } from "./lib/api";

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
        <App />
      </QueryClientProvider>
    </AuthProvider>
  </StrictMode>,
);
