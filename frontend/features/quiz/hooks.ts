"use client";

/** Quiz and attempt server state (docs/F2_GATE.md sections 4, 6, 12; gates GF2-02..21). */
import { useInfiniteQuery, useMutation, useQuery, useQueryClient, type InfiniteData, type QueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useRef, useState } from "react";
import { nextOffset } from "@/features/courses/hooks";
import { MAX_POLL_DELAY_MS, MAX_POLL_FAILURES, POLL_INTERVAL_MS, consecutiveFailures, newFailureTracker } from "@/features/documents/polling";
import { ApiError } from "@/lib/api/errors";
import type { AttemptDetail, AttemptResults, QuizList, QuizOut, SavedAnswer } from "@/lib/api/types";
import { ATTEMPT_PAGE_SIZE, QUIZ_PAGE_SIZE, queryKeys } from "@/lib/query/keys";
import {
  createQuiz,
  deleteQuiz,
  getAttempt,
  getQuiz,
  getResults,
  listAttempts,
  listQuizzes,
  regenerateQuiz,
  retryMissed,
  saveAnswer,
  startAttempt,
  submitAttempt,
  type AnswerPayload,
  type QuizRequest,
} from "./api";

/** Poll every 2 s while something is generating, with the F0-B backoff; stop after repeated failures (GF2-05). */
export function generationPollDelay(generating: boolean, failures: number): number | false {
  if (!generating || failures >= MAX_POLL_FAILURES) return false;
  return Math.min(POLL_INTERVAL_MS * 2 ** failures, MAX_POLL_DELAY_MS);
}

export function useQuizzes(courseId: string, { enabled = true }: { enabled?: boolean } = {}) {
  const tracker = useRef(newFailureTracker());
  return useInfiniteQuery({
    queryKey: queryKeys.quizList(courseId),
    queryFn: ({ pageParam, signal }) => listQuizzes(courseId, QUIZ_PAGE_SIZE, pageParam, signal),
    initialPageParam: 0,
    getNextPageParam: nextOffset,
    enabled,
    refetchInterval: (query) =>
      generationPollDelay(
        (query.state.data?.pages ?? []).some((p) => p.items.some((q) => q.status === "generating")),
        consecutiveFailures(tracker.current, query.state),
      ),
    refetchIntervalInBackground: false,
  });
}

export function useQuiz(quizId: string | null) {
  const tracker = useRef(newFailureTracker());
  const result = useQuery({
    queryKey: queryKeys.quiz(quizId ?? ""),
    queryFn: ({ signal }) => getQuiz(quizId!, signal),
    enabled: quizId !== null,
    refetchInterval: (query) => generationPollDelay(query.state.data?.status === "generating", consecutiveFailures(tracker.current, query.state)),
    refetchIntervalInBackground: false,
  });
  const failures = consecutiveFailures(tracker.current, { dataUpdatedAt: result.dataUpdatedAt, errorUpdateCount: result.errorUpdateCount });
  return {
    ...result,
    pollingStopped: result.data?.status === "generating" && failures >= MAX_POLL_FAILURES,
    resumePolling: () => {
      tracker.current.errorsAtSuccess = result.errorUpdateCount;
      void result.refetch();
    },
  };
}

function cacheQuiz(client: QueryClient, quiz: QuizOut) {
  // QuizOut has no questions; a generating, failed or invalid quiz has none either (backend: empty unless ready).
  client.setQueryData(queryKeys.quiz(quiz.id), { ...quiz, questions: [] });
  void client.invalidateQueries({ queryKey: queryKeys.quizzesOf(quiz.course_id) });
}

/** POST always creates a new quiz, so it is never retried and double submission is blocked by the caller. */
export function useCreateQuiz(courseId: string) {
  const client = useQueryClient();
  return useMutation({ mutationFn: (body: QuizRequest) => createQuiz(courseId, body), onSuccess: (quiz) => cacheQuiz(client, quiz) });
}

export function useRegenerateQuiz(quizId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => regenerateQuiz(quizId),
    onSuccess: (quiz) => {
      cacheQuiz(client, quiz);
      void client.invalidateQueries({ queryKey: queryKeys.attemptsOf(quizId) }); // in-progress attempts expired
    },
  });
}

export function useDeleteQuiz(quiz: Pick<QuizOut, "id" | "course_id">) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      try {
        await deleteQuiz(quiz.id);
      } catch (error) {
        if (!(error instanceof ApiError && error.kind === "not_found")) throw error;
      }
    },
    onSuccess: () => {
      client.setQueriesData<InfiniteData<QuizList, number>>({ queryKey: queryKeys.quizzesOf(quiz.course_id) }, (data) =>
        data ? { ...data, pages: data.pages.map((p) => ({ ...p, items: p.items.filter((q) => q.id !== quiz.id) })) } : data,
      );
      void client.invalidateQueries({ queryKey: queryKeys.quizzesOf(quiz.course_id) });
    },
  });
}

export function useAttempts(quizId: string, { enabled = true }: { enabled?: boolean } = {}) {
  return useInfiniteQuery({
    queryKey: queryKeys.attemptList(quizId),
    queryFn: ({ pageParam, signal }) => listAttempts(quizId, ATTEMPT_PAGE_SIZE, pageParam, signal),
    initialPageParam: 0,
    getNextPageParam: nextOffset,
    enabled,
  });
}

export function useAttempt(attemptId: string | null) {
  return useQuery({ queryKey: queryKeys.attempt(attemptId ?? ""), queryFn: ({ signal }) => getAttempt(attemptId!, signal), enabled: attemptId !== null });
}

/** 201 (new) or 200 (resumed): either way the response is the attempt to open. */
export function useStartAttempt(quizId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => startAttempt(quizId),
    onSuccess: (attempt) => {
      client.setQueryData(queryKeys.attempt(attempt.id), attempt);
      void client.invalidateQueries({ queryKey: queryKeys.attemptsOf(quizId) });
    },
  });
}

export function useRetryMissed(parent: Pick<AttemptResults, "attempt_id" | "quiz_id">) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => retryMissed(parent.attempt_id),
    onSuccess: (attempt) => {
      client.setQueryData(queryKeys.attempt(attempt.id), attempt);
      void client.invalidateQueries({ queryKey: queryKeys.attemptsOf(parent.quiz_id) });
    },
  });
}

/**
 * Results exist only for submitted attempts. This query is enabled only by the review page, which first checked the
 * attempt is submitted; the taking page never calls it (answer secrecy, GF2-11).
 */
export function useResults(attemptId: string, { enabled }: { enabled: boolean }) {
  return useQuery({ queryKey: queryKeys.attemptResults(attemptId), queryFn: ({ signal }) => getResults(attemptId, signal), enabled });
}

/** One POST per deliberate submit; the response (idempotent on the server) is the results cache (GF2-12). */
export function useSubmitAttempt(attempt: Pick<AttemptDetail, "id" | "quiz_id">) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => submitAttempt(attempt.id),
    onSuccess: (results) => {
      client.setQueryData(queryKeys.attemptResults(attempt.id), results);
      void client.invalidateQueries({ queryKey: queryKeys.attempt(attempt.id) });
      void client.invalidateQueries({ queryKey: queryKeys.attemptsOf(attempt.quiz_id) });
    },
  });
}

export type SaveState = { status: "idle" | "saving" | "saved" | "error"; error: unknown };

function samePayload(a: AnswerPayload | undefined, b: AnswerPayload | undefined): boolean {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
}

export function payloadOf(saved: SavedAnswer["answer"]): AnswerPayload | undefined {
  if (typeof saved.choice === "number") return { choice: saved.choice };
  if (typeof saved.value === "boolean") return { value: saved.value };
  return undefined;
}

/**
 * Answer saving (GF2-09): a choice is sent at once; while a question's request is in flight a newer choice waits and
 * is sent afterwards, so the last choice always wins and requests never race. An answer is "Saved" only after the
 * backend's 200. Failures are shown with Try again and are never retried automatically.
 */
export function useAnswerSaver(attempt: AttemptDetail, onRateLimited: (error: unknown) => void) {
  const client = useQueryClient();
  const initial = useMemo(() => new Map((attempt.answers ?? []).flatMap((a) => (payloadOf(a.answer) ? [[a.question_id, payloadOf(a.answer)!] as const] : []))), [attempt.answers]);
  const desired = useRef(new Map<string, AnswerPayload>(initial));
  const inflight = useRef(new Set<string>());
  const [choices, setChoices] = useState(() => new Map(initial));
  const [states, setStates] = useState(() => new Map<string, SaveState>([...initial.keys()].map((id) => [id, { status: "saved", error: null }])));

  const setState = useCallback((id: string, state: SaveState) => setStates((m) => new Map(m).set(id, state)), []);

  const send = useCallback(
    (id: string) => {
      const payload = desired.current.get(id);
      if (!payload || inflight.current.has(id)) return;
      inflight.current.add(id);
      setState(id, { status: "saving", error: null });
      saveAnswer(attempt.id, id, payload)
        .then((saved) => {
          inflight.current.delete(id);
          client.setQueryData<AttemptDetail>(queryKeys.attempt(attempt.id), (data) => {
            if (!data?.answers) return data;
            const answers = [...data.answers.filter((a) => a.question_id !== id), saved];
            return { ...data, answers, answered_count: answers.length };
          });
          if (samePayload(desired.current.get(id), payload)) setState(id, { status: "saved", error: null });
          else send(id); // a newer choice arrived while this one was in flight
        })
        .catch((error: unknown) => {
          inflight.current.delete(id);
          onRateLimited(error);
          setState(id, { status: "error", error });
        });
    },
    [attempt.id, client, onRateLimited, setState],
  );

  const choose = useCallback(
    (id: string, payload: AnswerPayload) => {
      desired.current.set(id, payload);
      setChoices((m) => new Map(m).set(id, payload));
      if (inflight.current.has(id)) setState(id, { status: "saving", error: null });
      else send(id);
    },
    [send, setState],
  );

  const unsettled = [...states.values()].some((s) => s.status === "saving" || s.status === "error");
  return { choices, states, choose, retry: send, unsettled };
}
