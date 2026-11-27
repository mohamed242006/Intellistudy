"use client";

/** Summary server state (gates GF1-01..05, GF1-19). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";
import { MAX_POLL_FAILURES, MAX_POLL_DELAY_MS, POLL_INTERVAL_MS, consecutiveFailures, newFailureTracker } from "@/features/documents/polling";
import type { CourseSummaryOut, SummaryOut } from "@/lib/api/types";
import { queryKeys } from "@/lib/query/keys";
import { createCourseSummary, deleteCourseSummary, getCourseSummary, getSummary, listCourseSummaries, requestSummary } from "./api";

/** Poll while a generation is queued or running (`pending`), with the same bounded backoff as document polling. */
export function summaryPollDelay(summary: Pick<SummaryOut, "pending"> | null | undefined, failures: number): number | false {
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

/** A combined summary; polled while it is being generated, like a single summary. */
export function useCourseSummary(summaryId: string, { enabled }: { enabled: boolean }) {
  const tracker = useRef(newFailureTracker());
  const result = useQuery({
    queryKey: queryKeys.courseSummary(summaryId),
    queryFn: ({ signal }) => getCourseSummary(summaryId, signal),
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

export function useCourseSummaries(courseId: string, { enabled }: { enabled: boolean }) {
  return useQuery({
    queryKey: queryKeys.courseSummariesOf(courseId),
    queryFn: ({ signal }) => listCourseSummaries(courseId, signal),
    enabled,
  });
}

/** POST once with the explicit selection. Never retried automatically; the caller keeps the selection on failure. */
export function useCreateCourseSummary(courseId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (documentIds: readonly string[]) => createCourseSummary(courseId, documentIds),
    onSuccess: (summary: CourseSummaryOut) => {
      client.setQueryData(queryKeys.courseSummary(summary.id), summary);
      void client.invalidateQueries({ queryKey: queryKeys.courseSummariesOf(courseId) });
    },
  });
}

export function useDeleteCourseSummary(courseId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (summaryId: string) => deleteCourseSummary(summaryId),
    onSuccess: (_, summaryId) => {
      client.removeQueries({ queryKey: queryKeys.courseSummary(summaryId) });
      void client.invalidateQueries({ queryKey: queryKeys.courseSummariesOf(courseId) });
    },
  });
}

export const singleSummaryHref = (courseId: string, documentId: string) =>
  `/courses/${encodeURIComponent(courseId)}/documents/${encodeURIComponent(documentId)}/summary`;
export const combinedSummaryHref = (summaryId: string) => `/summaries/${encodeURIComponent(summaryId)}`;

/**
 * Create a summary from the exact selected ids and resolve to the page that shows it. One file: that file's own
 * summary (POST /documents/{id}/summary; a stored one is returned as is). Two or more: ONE combined summary
 * (POST /courses/{id}/summaries with document_ids). Used by the workspace toolbar and the Create summary page.
 */
export function useCreateSummary(courseId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (ids: readonly string[]): Promise<string> => {
      const unique = [...new Set(ids)];
      if (unique.length === 1) {
        const summary = await requestSummary(unique[0]!, false);
        client.setQueryData(queryKeys.summary(unique[0]!), summary);
        return singleSummaryHref(courseId, unique[0]!);
      }
      const summary = await createCourseSummary(courseId, unique);
      client.setQueryData(queryKeys.courseSummary(summary.id), summary);
      void client.invalidateQueries({ queryKey: queryKeys.courseSummariesOf(courseId) });
      return combinedSummaryHref(summary.id);
    },
  });
}
