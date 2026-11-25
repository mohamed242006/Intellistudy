"use client";

/** Document server state: list with bounded polling, single document, retry, delete, download (GF0B-19..23). */
import { useInfiniteQuery, useMutation, useQuery, useQueryClient, type InfiniteData } from "@tanstack/react-query";
import { useMemo, useRef } from "react";
import { ApiError } from "@/lib/api/errors";
import type { DocumentList, DocumentOut } from "@/lib/api/types";
import { DOCUMENT_PAGE_SIZE, queryKeys } from "@/lib/query/keys";
import { nextOffset } from "@/features/courses/hooks";
import { deleteDocument, downloadDocument, getDocument, listDocuments, retryDocument } from "./api";
import { MAX_POLL_FAILURES, consecutiveFailures, newFailureTracker, pollDelay } from "./polling";
import { isInProgress } from "./status";

type Pages = InfiniteData<DocumentList, number>;

export function flatten(data: { pages: DocumentList[] } | undefined): DocumentOut[] {
  return data?.pages.flatMap((page) => page.items) ?? [];
}

/**
 * The documents of a course. With `poll`, this observer is the page's single poller (GF0B-19): the interval is
 * recomputed on every cache update, so it starts when a document enters processing and stops when all are terminal.
 */
export function useDocuments(courseId: string, { poll, enabled = true }: { poll: boolean; enabled?: boolean }) {
  const tracker = useRef(newFailureTracker());
  const result = useInfiniteQuery({
    queryKey: queryKeys.documentList(courseId),
    queryFn: ({ pageParam, signal }) => listDocuments(courseId, DOCUMENT_PAGE_SIZE, pageParam, signal),
    initialPageParam: 0,
    getNextPageParam: nextOffset,
    refetchInterval: poll ? (query) => pollDelay(flatten(query.state.data), consecutiveFailures(tracker.current, query.state)) : false,
    refetchIntervalInBackground: false,
    enabled,
  });
  const documents = useMemo(() => flatten(result.data), [result.data]);
  const failures = consecutiveFailures(tracker.current, { dataUpdatedAt: result.dataUpdatedAt, errorUpdateCount: result.errorUpdateCount });
  const pollingStopped = poll && failures >= MAX_POLL_FAILURES && documents.some((doc) => isInProgress(doc.status));
  return {
    ...result,
    documents,
    complete: result.isSuccess && !result.hasNextPage,
    pollingStopped,
    /** Manual "Try again" after polling stopped: forget the failures and fetch now. */
    resumePolling: () => {
      tracker.current.errorsAtSuccess = result.errorUpdateCount;
      void result.refetch();
    },
  };
}

/** A single document, used only for a `?file=` id that is not in the loaded pages. */
export function useDocument(documentId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.document(documentId ?? ""),
    queryFn: ({ signal }) => getDocument(documentId!, signal),
    enabled: enabled && documentId !== null,
  });
}

function mapPages(data: Pages | undefined, fn: (items: DocumentOut[]) => DocumentOut[]): Pages | undefined {
  return data ? { ...data, pages: data.pages.map((page) => ({ ...page, items: fn(page.items) })) } : data;
}

/** Put a document returned by the server into the course list (replace in place, or add on top). */
export function upsertDocument(client: ReturnType<typeof useQueryClient>, courseId: string, doc: DocumentOut) {
  client.setQueryData<Pages>(queryKeys.documentList(courseId), (data) => {
    if (!data) return data;
    const present = data.pages.some((page) => page.items.some((item) => item.id === doc.id));
    if (present) return mapPages(data, (items) => items.map((item) => (item.id === doc.id ? doc : item)));
    const [first, ...rest] = data.pages;
    return first ? { ...data, pages: [{ ...first, items: [doc, ...first.items] }, ...rest] } : data;
  });
  client.setQueryData(queryKeys.document(doc.id), doc);
}

export function useRetryDocument(courseId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (documentId: string) => retryDocument(documentId),
    onSuccess: (doc) => upsertDocument(client, courseId, doc),
  });
}

/** Delete; removed from the cache only after the backend confirmed (204), or reported it gone (404). */
export function useDeleteDocument(courseId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (documentId: string) => {
      try {
        await deleteDocument(documentId);
      } catch (error) {
        if (!(error instanceof ApiError && error.kind === "not_found")) throw error;
      }
      return documentId;
    },
    onSuccess: (documentId) => {
      client.setQueryData<Pages>(queryKeys.documentList(courseId), (data) => mapPages(data, (items) => items.filter((item) => item.id !== documentId)));
      client.removeQueries({ queryKey: queryKeys.document(documentId) });
      void client.invalidateQueries({ queryKey: queryKeys.documentsOf(courseId) });
    },
  });
}

/** How long an object URL lives after the download starts before it is revoked. */
export const OBJECT_URL_TTL_MS = 1_000;

/** Save a Blob through a programmatic anchor; the object URL is always revoked (GF0B-22). */
export function saveBlob(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = fileName;
    anchor.rel = "noopener";
    anchor.style.display = "none";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), OBJECT_URL_TTL_MS);
  }
}

export function useDownloadDocument() {
  return useMutation({
    mutationFn: async (doc: Pick<DocumentOut, "id" | "file_name">) => {
      const { blob, fileName } = await downloadDocument(doc.id);
      saveBlob(blob, fileName ?? doc.file_name);
    },
  });
}
