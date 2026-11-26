"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { Button } from "@/design-system/components/Button";
import { Modal } from "@/design-system/components/Modal";
import { Notice } from "@/design-system/components/Notice";
import { useToast } from "@/design-system/components/Toast";
import { Breadcrumb } from "@/design-system/compositions/Breadcrumb";
import { FormAlert } from "@/features/auth/components/FormAlert";
import { useCourse } from "@/features/courses/hooks";
import { useDocuments } from "@/features/documents/hooks";
import { FIGMA as COURSE_FIGMA } from "@/features/courses/strings";
import { ResourceNotFound } from "@/features/shell/components/ResourceNotFound";
import { ApiError } from "@/lib/api/errors";
import type { AttemptOut } from "@/lib/api/types";
import { relativeTime } from "@/lib/format/format";
import { useNow } from "@/lib/format/use-now";
import { useRetryAfter } from "@/lib/hooks/use-retry-after";
import { useAttempts, useDeleteQuiz, useQuiz, useRegenerateQuiz, useStartAttempt } from "../hooks";
import { generationFailure, quizError } from "../messages";
import { FIGMA, PROVISIONAL } from "../strings";
import { QuizStatusTag } from "./QuizListPage";

export const CANONICAL_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export function attemptHref(attempt: Pick<AttemptOut, "id" | "quiz_id" | "status">): string {
  return attempt.status === "submitted" ? `/attempts/${encodeURIComponent(attempt.id)}/review` : `/quizzes/${encodeURIComponent(attempt.quiz_id)}/attempts/${encodeURIComponent(attempt.id)}`;
}

/** Quiz page (gates GF2-05..07, GF2-18, GF2-20): status, start or continue, regenerate, delete, attempt history. */
export function QuizPage({ quizId }: { quizId: string }) {
  if (!CANONICAL_ID.test(quizId)) return <ResourceNotFound />; // never requested (GF2-20)
  return <QuizPageInner quizId={quizId} />;
}

function QuizPageInner({ quizId }: { quizId: string }) {
  const router = useRouter();
  const toast = useToast();
  const now = useNow();
  const quiz = useQuiz(quizId);
  const course = useCourse(quiz.data?.course_id ?? "", { enabled: Boolean(quiz.data) });
  const files = useDocuments(quiz.data?.course_id ?? "", { poll: false, enabled: Boolean(quiz.data) });
  const attempts = useAttempts(quizId, { enabled: quiz.isSuccess });
  const start = useStartAttempt(quizId);
  const regenerate = useRegenerateQuiz(quizId);
  const remove = useDeleteQuiz({ id: quizId, course_id: quiz.data?.course_id ?? "" });
  const retryAfter = useRetryAfter();
  const [dialog, setDialog] = useState<null | "regenerate" | "delete">(null);
  const [problem, setProblem] = useState<string | null>(null);
  const cancel = useRef<HTMLButtonElement>(null);

  if (quiz.isError && quiz.error instanceof ApiError && quiz.error.kind === "not_found") return <ResourceNotFound />;
  if (quiz.isPending) return <div aria-busy="true" role="status" aria-label={PROVISIONAL.loading} className="min-h-[50vh]" />;
  if (quiz.isError) {
    return (
      <div role="alert" className="flex flex-col items-start gap-4 px-4 py-10 lg:px-12">
        <Notice tone="warning" title={PROVISIONAL.loadError} />
        <Button variant="secondary" onClick={() => void quiz.refetch()}>
          {PROVISIONAL.tryAgain}
        </Button>
      </div>
    );
  }

  const data = quiz.data;
  const history = attempts.data?.pages.flatMap((p) => p.items) ?? [];
  const inProgress = history.find((a) => a.status === "in_progress");
  const begin = () => {
    if (start.isPending || retryAfter.blocked) return;
    setProblem(null);
    start.mutate(undefined, {
      onSuccess: (attempt) => router.push(attemptHref(attempt)),
      onError: (error) => {
        retryAfter.note(error);
        setProblem(quizError(error));
      },
    });
  };
  const fewer = data.status === "ready" && data.question_count < data.requested_count;

  return (
    <div className="mx-auto flex w-full max-w-[1080px] flex-col gap-6 px-4 py-6 md:px-8 lg:px-12 lg:pt-8 lg:pb-12">
      <Breadcrumb
        items={[
          { label: COURSE_FIGMA.courses, href: "/#courses" },
          ...(course.data ? [{ label: course.data.name, href: `/courses/${encodeURIComponent(course.data.id)}` }] : []),
          { label: PROVISIONAL.quizzes, href: `/courses/${encodeURIComponent(data.course_id)}/quizzes` },
          { label: data.title },
        ]}
      />
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-2">
          <h1 className="text-h1 break-words text-fg">{data.title}</h1>
          <span className="flex flex-wrap items-center gap-2">
            <QuizStatusTag status={data.status} />
            {data.status === "ready" ? <span className="text-body-sm text-fg-secondary">{PROVISIONAL.questionsCount(data.question_count)}</span> : null}
          </span>
          <SourceFiles ids={data.source_document_ids} names={new Map(files.documents.map((d) => [d.id, d.file_name]))} />
        </div>
        <div className="flex flex-wrap gap-3">
          {data.status === "ready" ? (
            <Button loading={start.isPending} disabled={retryAfter.blocked} onClick={begin}>
              {inProgress ? PROVISIONAL.continueQuiz : FIGMA.startQuiz}
            </Button>
          ) : null}
          {data.status !== "generating" ? (
            <Button variant="secondary" onClick={() => setDialog("regenerate")}>
              {PROVISIONAL.regenerate}
            </Button>
          ) : null}
          <Button variant="secondary" onClick={() => setDialog("delete")}>
            {PROVISIONAL.deleteQuiz}
          </Button>
        </div>
      </div>

      <div role="alert" className="empty:sr-only">
        {problem ? <Notice tone="warning" title={problem} /> : null}
      </div>
      <div role="status" className="empty:sr-only">
        {data.status === "generating" ? <Notice tone="info" title={PROVISIONAL.generatingTitle} body={PROVISIONAL.generatingBody} /> : null}
      </div>
      {quiz.pollingStopped ? (
        <div role="alert" className="flex flex-col items-start gap-3">
          <Notice tone="warning" title={PROVISIONAL.pollingStopped} body={PROVISIONAL.pollingStoppedBody} />
          <Button variant="secondary" onClick={quiz.resumePolling}>
            {PROVISIONAL.tryAgain}
          </Button>
        </div>
      ) : null}
      {data.status === "failed" ? <Notice tone="warning" title={PROVISIONAL.failedTitle} body={generationFailure(data.error_code)} /> : null}
      {data.status === "invalid" ? <Notice tone="warning" title={PROVISIONAL.invalidTitle} body={data.notice ?? undefined} /> : null}
      {fewer ? <Notice tone="info" title={PROVISIONAL.fewer(data.question_count, data.requested_count)} /> : null}

      <section aria-labelledby="attempts-heading" className="flex flex-col gap-3">
        <h2 id="attempts-heading" className="text-h3 text-fg">
          {PROVISIONAL.attempts}
        </h2>
        {attempts.isPending ? <div aria-busy="true" role="status" aria-label={PROVISIONAL.loading} className="h-12" /> : null}
        {attempts.isSuccess && history.length === 0 ? <p className="text-body text-fg-secondary">{PROVISIONAL.noAttempts}</p> : null}
        <ul className="flex flex-col gap-2">
          {history.map((attempt) => (
            <li key={attempt.id}>
              <Link href={attemptHref(attempt)} className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-line bg-surface px-4 py-3 hover:bg-subtle">
                <span className="text-label text-fg">{PROVISIONAL.attemptStatus[attempt.status] ?? PROVISIONAL.unknownStatus}</span>
                <span className="text-body-sm text-fg-secondary">
                  {attempt.status === "submitted" && attempt.score !== null ? FIGMA.correctOf(attempt.score, attempt.max_score) : PROVISIONAL.answeredOf(attempt.answered_count, attempt.question_count)}
                </span>
                {attempt.parent_attempt_id ? <span className="text-caption text-fg-secondary">{PROVISIONAL.retryOf}</span> : null}
                <span className="ml-auto text-caption text-fg-secondary">{relativeTime(attempt.started_at, now)}</span>
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <Modal
        open={dialog !== null}
        busy={regenerate.isPending || remove.isPending}
        initialFocus={cancel}
        title={dialog === "delete" ? PROVISIONAL.deleteTitle : PROVISIONAL.regenerateTitle}
        description={dialog === "delete" ? PROVISIONAL.deleteBody : PROVISIONAL.regenerateBody}
        onClose={() => setDialog(null)}
        footer={
          <>
            <Button ref={cancel} variant="secondary" disabled={regenerate.isPending || remove.isPending} onClick={() => setDialog(null)}>
              {PROVISIONAL.cancel}
            </Button>
            {dialog === "delete" ? (
              <Button
                variant="danger"
                loading={remove.isPending}
                onClick={() =>
                  !remove.isPending &&
                  remove.mutate(undefined, {
                    onSuccess: () => {
                      setDialog(null);
                      toast(PROVISIONAL.quizDeleted, "success");
                      router.replace(`/courses/${encodeURIComponent(data.course_id)}/quizzes`);
                    },
                  })
                }
              >
                {PROVISIONAL.deleteQuiz}
              </Button>
            ) : (
              <Button
                loading={regenerate.isPending}
                disabled={retryAfter.blocked}
                onClick={() =>
                  !regenerate.isPending &&
                  regenerate.mutate(undefined, {
                    onSuccess: () => setDialog(null),
                    onError: (error) => retryAfter.note(error),
                  })
                }
              >
                {PROVISIONAL.regenerate}
              </Button>
            )}
          </>
        }
      >
        <FormAlert message={regenerate.isError ? quizError(regenerate.error) : remove.isError ? quizError(remove.error) : null} />
      </Modal>
    </div>
  );
}

/** The files this quiz was written from (its stored sources), so a multi-file quiz says which files it covers. */
function SourceFiles({ ids, names }: { ids: readonly string[]; names: ReadonlyMap<string, string> }) {
  const known = ids.map((id) => names.get(id)).filter((name): name is string => Boolean(name));
  if (!known.length) return null;
  return (
    <p className="min-w-0 text-body-sm wrap-anywhere text-fg-secondary">
      <span className="text-caption-strong">{ids.length === 1 ? "SOURCE FILE: " : `${ids.length} SOURCE FILES: `}</span>
      {known.join(" · ")}
    </p>
  );
}
