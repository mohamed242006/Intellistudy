import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { StrictMode, type ReactNode } from "react";
import { AuthProvider } from "@/lib/auth/auth-provider";
import { createQueryClient } from "@/lib/query/query-client";

export function renderWithProviders(ui: ReactNode, queryClient: QueryClient = createQueryClient()) {
  return {
    queryClient,
    ...render(
      <StrictMode>
        <QueryClientProvider client={queryClient}>
          <AuthProvider>{ui}</AuthProvider>
        </QueryClientProvider>
      </StrictMode>,
    ),
  };
}
