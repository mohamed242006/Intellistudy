import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { StrictMode, type ReactNode } from "react";
import { ToastProvider } from "@/design-system/components/Toast";
import { AuthProvider } from "@/lib/auth/auth-provider";
import { createQueryClient } from "@/lib/query/query-client";

/** The app's query client with retry delays shortened for tests (the retry rules themselves are unchanged). */
export function testQueryClient(): QueryClient {
  const client = createQueryClient();
  const defaults = client.getDefaultOptions();
  client.setDefaultOptions({ ...defaults, queries: { ...defaults.queries, retryDelay: 1 } });
  return client;
}

export function renderWithProviders(ui: ReactNode, queryClient: QueryClient = createQueryClient()) {
  return {
    queryClient,
    ...render(
      <StrictMode>
        <QueryClientProvider client={queryClient}>
          <AuthProvider>
            <ToastProvider>{ui}</ToastProvider>
          </AuthProvider>
        </QueryClientProvider>
      </StrictMode>,
    ),
  };
}
