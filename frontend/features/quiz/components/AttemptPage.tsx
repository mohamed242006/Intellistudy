"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { AnswerChoice } from "@/design-system/components/AnswerOption";
import { Button, ButtonLink } from "@/design-system/components/Button";
import { Modal } from "@/design-system/components/Modal";
import { Notice } from "@/design-system/components/Notice";
import { QuizBar } from "@/design-system/compositions/QuizBar";
import { FormAlert } from "@/features/auth/components/FormAlert";
import { useCourse } from "@/features/courses/hooks";
import { ResourceNotFound } from "@/features/shell/components/ResourceNotFound";
import { ApiError } from "@/lib/api/errors";
import type { AttemptDetail, QuestionOut } from "@/lib/api/types";
import { useRetryAfter } from "@/lib/hooks/use-retry-after";
import type { AnswerPayload } from "../api";
import { useAnswerSaver, useAttempt, useQuiz, useSubmitAttempt, type SaveState } from "../hooks";
import { quizError } from "../messages";
import { FIGMA, PROVISIONAL } from "../strings";
import { CANONICAL_ID } from "./QuizPage";

/** Taking a quiz (gates GF2-07..13, GF2-17, GF2-20). Only public question fields exist here: no key, no verdict. */
export function AttemptPage({ quizId, attemptId }: { quizId: string; attemptId: string }) {
  if (!CANONICAL_ID.test(quizId) || !CANONICAL_ID.test(attemptId)) return <ResourceNotFound />;
  return <AttemptLoader quizId={quizId} attemptId={attemptId} />;
}

function AttemptLoader({ quizId, attemptId }: { quizId: string; attemptId: string }) {
  const router = useRouter();
  const attempt = useAttempt(attemptId);
  const quiz = useQuiz(quizId);
  const course = useCourse(quiz.data?.course_id ?? "", { enabled: Boolean(quiz.data) });
  const submitted = attempt.data?.status === "submitted" && attempt.data.quiz_id === quizId;

  useEffect(() => {
    if (submitted) router.replace(`/attempts/${encodeURIComponent(attemptId)}/review`);
  }, [submitted, attemptId, router]);

  const notFound = (q: { isError: boolean; error: unknown }) => q.isError && q.error instanceof ApiError && q.error.kind === "not_found";
  if (notFound(attempt) || notFound(quiz) || (attempt.data && attempt.data.quiz_id !== quizId)) return <ResourceNotFound />;
  if (attempt.isPending || quiz.isPending || submitted) return <div aria-busy="true" role="status" aria-label={PROVISIONAL.loading} className="min-h-[50vh]" />;
  if (attempt.isError || quiz.isError) {
    return (
      <div role="alert" className="flex flex-col items-start gap-4 px-4 py-10 lg:px-12">
        <Notice tone="warning" title={PROVISIONAL.loadError} />
        <Button variant="secondary" onClick={() => void Promise.all([attempt.refetch(), quiz.refetch()])}>
          {PROVISIONAL.tryAgain}
        </Button>
      </div>
    );
  }
  const quizHref = `/quizzes/${encodeURIComponent(quizId)}`;
  if (attempt.data.status !== "in_progress" || !attempt.data.questions) {
    return (
      <div className="flex flex-col items-start gap-4 px-4 py-10 lg:px-12">
        <h1 className="text-h2 text-fg">{PROVISIONAL.expiredTitle}</h1>
        <Notice tone="warning" title={PROVISIONAL.expiredTitle} body={PROVISIONAL.expiredBody} />
        <ButtonLink href={quizHref}>{PROVISIONAL.backToQuiz}</ButtonLink>
      </div>
    );
  }
  return <Taking key={attempt.data.id} attempt={attempt.data} quizTitle={quiz.data.title} courseName={course.data?.name ?? ""} quizHref={quizHref} />;
}

function saveText(state: SaveState | undefined): string {
  if (!state || state.status === "idle") return "";
  if (state.status === "saving") return PROVISIONAL.saving;
  if (state.status === "saved") return PROVISIONAL.saved;
  return PROVISIONAL.notSaved(quizError(state.error));
}

function Taking({ attempt, quizTitle, courseName, quizHref }: { attempt: AttemptDetail; quizTitle: string; courseName: string; quizHref: string }) {
  const router = useRouter();
  const questions = attempt.questions ?? [];
  const retryAfter = useRetryAfter();
  const saver = useAnswerSaver(attempt, retryAfter.note);
  const submit = useSubmitAttempt(attempt);
  // Resume at the first question without a saved answer (or the first question).
  const [index, setIndex] = useState(() => Math.max(0, questions.findIndex((q) => !saver.choices.has(q.id))));
  const [dialog, setDialog] = useState<null | "submit" | "exit">(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const moved = useRef(false);
  const cancel = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (moved.current) heading.current?.focus(); // focus follows the question, not on first render
  }, [index]);

  const question = questions[index];
  const total = questions.length;
  const go = (next: number) => {
    moved.current = true;
    setIndex(Math.min(Math.max(next, 0), total - 1));
  };
  const answered = questions.filter((q) => saver.states.get(q.id)?.status === "saved").length;
  const saving = [...saver.states.values()].some((s) => s.status === "saving");

  return (
    <div className="flex min-h-screen flex-col">
      <QuizBar
        exit={
          <Button variant="secondary" onClick={() => (saver.unsettled ? setDialog("exit") : router.push(quizHref))}>
            {FIGMA.exitQuiz}
          </Button>
        }
        title={courseName ? FIGMA.quizTitle(courseName) : quizTitle}
        subtitle={`${quizTitle} · ${PROVISIONAL.questionsCount(total)}`}
        position={question ? FIGMA.questionOf(index + 1, total) : ""}
        progress={total ? ((index + 1) / total) * 100 : 0}
        progressLabel={question ? FIGMA.questionOf(index + 1, total) : PROVISIONAL.navigator}
      />
      <div className="mx-auto flex w-full max-w-[720px] flex-col gap-6 px-4 py-8 lg:py-12">
        <nav aria-label={PROVISIONAL.navigator} className="flex flex-col gap-2">
          <p className="text-body-sm text-fg-secondary">{PROVISIONAL.answeredOf(answered, total)}</p>
          <ol className="flex flex-wrap gap-2">
            {questions.map((q, i) => {
              const done = saver.states.get(q.id)?.status === "saved";
              return (
                <li key={q.id}>
                  <button
                    type="button"
                    aria-label={PROVISIONAL.navItem(i + 1, done)}
                    aria-current={i === index ? "step" : undefined}
                    onClick={() => go(i)}
                    className={[
                      "flex size-11 items-center justify-center rounded-md border text-label",
                      done ? "border-accent-subtle-border bg-accent-subtle text-accent-fg" : "border-line-strong bg-surface text-fg",
                      i === index ? "shadow-[inset_0_0_0_2px_var(--color-accent)]" : "",
                    ].join(" ")}
                  >
                    {i + 1}
                  </button>
                </li>
              );
            })}
          </ol>
        </nav>

        {question ? (
          <QuestionView
            key={question.id}
            question={question}
            headingRef={heading}
            choice={saver.choices.get(question.id)}
            state={saver.states.get(question.id)}
            blocked={retryAfter.blocked}
            onChoose={(payload) => saver.choose(question.id, payload)}
            onRetry={() => saver.retry(question.id)}
          />
        ) : null}

        <div className="flex flex-wrap items-center gap-3">
          <Button variant="secondary" disabled={index === 0} onClick={() => go(index - 1)}>
            {FIGMA.previous}
          </Button>
          {index < total - 1 ? (
            <Button variant="ghost" onClick={() => go(index + 1)}>
              {FIGMA.skipQuestion}
            </Button>
          ) : null}
          <span className="flex-1" />
          {index < total - 1 ? (
            <Button onClick={() => go(index + 1)}>{PROVISIONAL.next}</Button>
          ) : null}
          <Button variant={index < total - 1 ? "secondary" : "primary"} onClick={() => setDialog("submit")}>
            {PROVISIONAL.finish}
          </Button>
        </div>
      </div>

      <Modal
        open={dialog === "submit"}
        busy={submit.isPending}
        initialFocus={cancel}
        title={PROVISIONAL.submitTitle}
        description={PROVISIONAL.submitBody(total - answered)}
        onClose={() => setDialog(null)}
        footer={
          <>
            <Button ref={cancel} variant="secondary" disabled={submit.isPending} onClick={() => setDialog(null)}>
              {PROVISIONAL.cancel}
            </Button>
            <Button
              loading={submit.isPending}
              disabled={saving || retryAfter.blocked}
              onClick={() => {
                if (submit.isPending || saving) return;
                submit.mutate(undefined, {
                  onSuccess: () => router.replace(`/attempts/${encodeURIComponent(attempt.id)}/review`),
                  onError: (error) => retryAfter.note(error),
                });
              }}
            >
              {PROVISIONAL.submit}
            </Button>
          </>
        }
      >
        <FormAlert message={submit.isError ? quizError(submit.error) : saving ? PROVISIONAL.saving : null} />
      </Modal>
      <Modal
        open={dialog === "exit"}
        title={PROVISIONAL.exitTitle}
        description={PROVISIONAL.exitBody}
        onClose={() => setDialog(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setDialog(null)}>
              {PROVISIONAL.stay}
            </Button>
            <Button onClick={() => router.push(quizHref)}>{PROVISIONAL.leave}</Button>
          </>
        }
      />
    </div>
  );
}

function QuestionView({ question, headingRef, choice, state, blocked, onChoose, onRetry }: {
  question: QuestionOut;
  headingRef: React.RefObject<HTMLHeadingElement | null>;
  choice: AnswerPayload | undefined;
  state: SaveState | undefined;
  blocked: boolean;
  onChoose: (payload: AnswerPayload) => void;
  onRetry: () => void;
}) {
  const name = `answer-${question.id}`;
  const mcq = question.type === "mcq" && Array.isArray(question.options) && question.options.length === 4;
  const tf = question.type === "true_false";
  return (
    <fieldset className="flex min-w-0 flex-col gap-4" data-question={question.position}>
      <legend className="flex w-full flex-col">
        <span className="mb-2 block text-caption-strong text-fg-secondary">{mcq ? FIGMA.multipleChoice : tf ? PROVISIONAL.trueFalse : ""}</span>
        <h2 ref={headingRef} tabIndex={-1} className="block text-h2 break-words text-fg outline-none">
          {question.stem}
        </h2>
      </legend>
      {mcq ? (
        <>
          <p className="text-body text-fg-secondary">{FIGMA.chooseOne}</p>
          <div className="flex flex-col gap-3">
            {question.options!.map((option, i) => (
              <AnswerChoice key={i} name={name} value={String(i)} label={option} checked={choice !== undefined && "choice" in choice && choice.choice === i} disabled={blocked} onChange={() => onChoose({ choice: i })} />
            ))}
          </div>
        </>
      ) : tf ? (
        <>
          <p className="text-body text-fg-secondary">{PROVISIONAL.trueFalseHint}</p>
          <div className="flex flex-col gap-3">
            {[true, false].map((value) => (
              <AnswerChoice key={String(value)} name={name} value={String(value)} label={value ? PROVISIONAL.true : PROVISIONAL.false} checked={choice !== undefined && "value" in choice && choice.value === value} disabled={blocked} onChange={() => onChoose({ value })} />
            ))}
          </div>
        </>
      ) : (
        <Notice tone="neutral" title={PROVISIONAL.unsupportedType} />
      )}
      <div className="flex min-h-11 flex-wrap items-center gap-3">
        <p role="status" className={`text-body-sm ${state?.status === "error" ? "text-danger-fg" : "text-fg-secondary"}`}>
          {saveText(state)}
        </p>
        {state?.status === "error" ? (
          <Button variant="secondary" disabled={blocked} onClick={onRetry}>
            {PROVISIONAL.tryAgain}
          </Button>
        ) : null}
      </div>
    </fieldset>
  );
}
