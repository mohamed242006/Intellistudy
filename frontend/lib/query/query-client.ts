import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api/errors";

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        // auth failures are handled by the API client (one refresh, one retry); never retry them here
        retry: (failures, error) =>
          !(error instanceof ApiError && ["session_expired", "unauthorized", "forbidden", "not_found"].includes(error.kind)) &&
          failures < 2,
      },
      mutations: { retry: false },
    },
  });
}
