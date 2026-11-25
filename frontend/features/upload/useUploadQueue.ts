"use client";

/**
 * Upload scheduler (gate GF0B-15, GF0B-16):
 * - one transfer at a time, one request per file (the backend validates each request all or nothing);
 * - no new transfer while the course already has MAX_ACTIVE documents processing (the backend allows 5 active jobs per
 *   user, `max_queued_jobs_per_user`); `queue_full` from the server puts the row back to Waiting until capacity frees,
 *   or, when nothing in this course is processing (the jobs belong to other courses), shows Retry;
 * - `rate_limited` pauses automatic starts until `Retry-After` has passed;
 * - in-flight transfers are aborted when the page unmounts; accepted files keep processing on the server.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { useToast } from "@/design-system/components/Toast";
import { ApiError } from "@/lib/api/errors";
import { UploadAbortedError, uploadFile } from "@/lib/api/upload";
import { upsertDocument } from "@/features/documents/hooks";
import { PROVISIONAL } from "@/features/documents/strings";
import { initialQueue, nextPending, problemForError, queueReducer } from "./queue";

export type { UploadItem } from "./queue";

export const MAX_ACTIVE = 5;
const DEFAULT_RATE_PAUSE_S = 60;

let counter = 0;
function makeId(): string {
  counter += 1;
  return `upload-${counter}`;
}

export function useUploadQueue(courseId: string, activeCount: number) {
  const [state, dispatch] = useReducer(queueReducer, initialQueue);
  const [announcement, setAnnouncement] = useState("");
  const [pausedUntil, setPausedUntil] = useState(0);
  /** Active count observed when the server answered queue_full; starts resume once the count drops below it. */
  const [capacityMark, setCapacityMark] = useState<number | null>(null);
  const controllers = useRef(new Map<string, AbortController>());
  const client = useQueryClient();
  const toast = useToast();
  const uploading = state.items.some((item) => item.phase === "uploading");

  useEffect(() => {
    const pending = controllers.current;
    return () => {
      for (const controller of pending.values()) controller.abort();
      pending.clear();
    };
  }, []);

  // Capacity freed since the queue_full answer: allow starts again.
  useEffect(() => {
    if (capacityMark !== null && activeCount < capacityMark) setCapacityMark(null);
  }, [activeCount, capacityMark]);

  // Rate-limit pause: wake up when it ends.
  const [, wake] = useReducer((n: number) => n + 1, 0);
  useEffect(() => {
    if (pausedUntil <= Date.now()) return;
    const timer = setTimeout(wake, pausedUntil - Date.now());
    return () => clearTimeout(timer);
  }, [pausedUntil]);

  const blockedByCapacity = capacityMark !== null || activeCount >= MAX_ACTIVE;
  /** Changes when a row is added, removed or changes phase; progress events do not change it. */
  const phases = state.items.map((item) => `${item.id}:${item.phase}`).join();

  useEffect(() => {
    if (uploading || blockedByCapacity || pausedUntil > Date.now()) return;
    const item = nextPending(state);
    if (!item) return;
    const controller = new AbortController();
    controllers.current.set(item.id, controller);
    dispatch({ type: "start", id: item.id });
    let lastPercent = 0;
    uploadFile(
      courseId,
      item.file,
      ({ loaded, total }) => {
        const percent = total > 0 ? Math.min(100, Math.floor((loaded / total) * 100)) : 0;
        if (percent !== lastPercent) {
          lastPercent = percent;
          dispatch({ type: "progress", id: item.id, percent });
        }
      },
      controller.signal,
    )
      .then((response) => {
        dispatch({ type: "accepted", id: item.id });
        for (const doc of response.documents) {
          const { duplicate, ...document } = doc;
          upsertDocument(client, courseId, document);
          if (duplicate) toast(PROVISIONAL.duplicate(document.file_name));
        }
        setAnnouncement(PROVISIONAL.uploadedAnnouncement(item.file.name));
      })
      .catch((error: unknown) => {
        if (error instanceof UploadAbortedError) {
          dispatch({ type: "remove", id: item.id });
          void client.invalidateQueries({ queryKey: ["documents", courseId] }); // the server may have accepted it
          return;
        }
        if (error instanceof ApiError && error.code === "queue_full" && activeCount > 0) {
          dispatch({ type: "requeue", id: item.id });
          setCapacityMark(activeCount);
          return;
        }
        if (error instanceof ApiError && error.code === "rate_limited") {
          setPausedUntil(Date.now() + (error.retryAfterSeconds ?? DEFAULT_RATE_PAUSE_S) * 1000);
        }
        const problem = problemForError(error);
        dispatch({ type: "problem", id: item.id, problem });
        setAnnouncement(PROVISIONAL.rejectedAnnouncement(item.file.name, problem.message));
      })
      .finally(() => controllers.current.delete(item.id));
    // `state` changes on every progress event; `phases` captures the changes that decide whether to start a file
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uploading, blockedByCapacity, pausedUntil, phases, courseId]);

  const add = useCallback((files: File[]) => dispatch({ type: "add", files, makeId }), []);
  const retry = useCallback((id: string) => dispatch({ type: "retry", id }), []);
  const remove = useCallback((id: string) => {
    const controller = controllers.current.get(id);
    if (controller) controller.abort(); // the abort handler removes the row
    else dispatch({ type: "remove", id });
  }, []);

  return { items: state.items, add, retry, remove, announcement, blockedByCapacity, paused: pausedUntil > Date.now() };
}
