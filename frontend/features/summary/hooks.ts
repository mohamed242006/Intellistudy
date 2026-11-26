"use client";

/** Summary server state (gates GF1-01..05, GF1-19). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";
import { MAX_POLL_FAILURES, MAX_POLL_DELAY_MS, POLL_INTERVAL_MS, consecutiveFailures, newFailureTracker } from "@/features/documents/polling";
import type { SummaryOut } from "@/lib/api/types";
import { queryKeys } from "@/lib/query/keys";
import { getSummary, requestSummary } from "./api";

/** Poll while a generation is queued or running (`pending`), with the same bounded backoff as document polling. */
export function summaryPollDelay(summary: SummaryOut | null | undefined, failures: number): number | false {
  if (!summary?.pending || failures >= MAX_POLL_FAILURES) return false;
  return Math.min(POLL_INTERVAL_MS * 2 ** failures, MAX_POLL_DELAY_MS);
}

export function useSummary(documentId: string, { enabled }: { enabled: boolean }) {
  const tracker = useRef(newFailureTracker());
  const result = useQuery({
    queryKey: queryKeys.summary(documentId),
    queryFn: ({ signal }) => getSummary(documentId, signal),
    enabled,
    refetchInterval: (query) => summaryPollDelay(query.state.data, consecutiveFailures(tracker.current, query.state)),
    refetchIntervalInBackground: false,
  });
  const failures = consecutiveFailures(tracker.current, { dataUpdatedAt: result.dataUpdatedAt, errorUpdateCount: result.errorUpdateCount });
  return {
    ...result,
    pollingStopped: Boolean(result.data?.pending) && failures >= MAX_POLL_FAILURES,
    resumePolling: () => {
      tracker.current.errorsAtSuccess = result.errorUpdateCount;
      void result.refetch();
    },
  };
}

/** POST once; the 200 or 202 response is the new cache value (no extra request). Never retried automatically. */
export function useRequestSummary(documentId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (regenerate: boolean) => requestSummary(documentId, regenerate),
    onSuccess: (summary) => client.setQueryData(queryKeys.summary(documentId), summary),
  });
}
