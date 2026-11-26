"use client";

import { useRouter } from "next/navigation";
import { useId, useState } from "react";
import { AnswerReviewRow, type ReviewVerdict } from "@/design-system/components/AnswerOption";
import { Button, ButtonLink } from "@/design-system/components/Button";
import { Notice } from "@/design-system/components/Notice";
import { SourceCard } from "@/design-system/components/SourceCard";
import { Tag, type TagTone } from "@/design-system/components/Tag";
import { QuizBar } from "@/design-system/compositions/QuizBar";
import { Icon } from "@/design-system/icons/Icon";
import { useCourse } from "@/features/courses/hooks";
import { ResourceNotFound } from "@/features/shell/components/ResourceNotFound";
import { ApiError } from "@/lib/api/errors";
import type { AttemptResults, ResultQuestion } from "@/lib/api/types";
import { useRetryAfter } from "@/lib/hooks/use-retry-after";
import { useAttempt, useQuiz, useResults, useRetryMissed, useStartAttempt } from "../hooks";
import { quizError } from "../messages";
import { FIGMA, PROVISIONAL } from "../strings";
import { CANONICAL_ID, attemptHref } from "./QuizPage";

export type QuestionVerdict = { tone: TagTone; label: string };

/** The backend's verdict, never re-judged: `correct` → Correct; not answered → Not answered; else Incorrect (GF2-15). */
export function verdictOf(result: Pick<ResultQuestion, "correct" | "answered">): QuestionVerdict {
  if (result.correct === true) return { tone: "success", label: FIGMA.correct };
  if (result.answered === false) return { tone: "neutral", label: PROVISIONAL.notAnswered };
  return { tone: "danger", label: FIGMA.incorrect };
}

/** Review rows for one question, from the backend's answer and correct answer only. Null when the shape is unknown. */
export function reviewRows(result: ResultQuestion): { label: string; verdict: ReviewVerdict; verdictText?: string; note?: string }[] | null {
  const mine = result.answer;
  const key = result.correct_answer;
  if (result.type === "mcq" && Array.isArray(result.options) && typeof key.choice === "number") {
    return result.options.map((label, i) => {
      const chosen = typeof mine?.choice === "number" && mine.choice === i;
      if (i === key.choice) return { label, verdict: "correct", verdictText: FIGMA.correct, note: chosen ? PROVISIONAL.yourAnswer : undefined };
      if (chosen) return { label, verdict: "incorrect", verdictText: FIGMA.incorrect, note: PROVISIONAL.yourAnswer };
      return { label, verdict: "neutral" };
    });
  }
  if (result.type === "true_false" && typeof key.value === "boolean") {
    return [true, false].map((value) => {
      const label = value ? PROVISIONAL.true : PROVISIONAL.false;
      const chosen = typeof mine?.value === "boolean" && mine.value === value;
      if (value === key.value) return { label, verdict: "correct", verdictText: FIGMA.correct, note: chosen ? PROVISIONAL.yourAnswer : undefined };
      if (chosen) return { label, verdict: "incorrect", verdictText: FIGMA.incorrect, note: PROVISIONAL.yourAnswer };
      return { label, verdict: "neutral" };
    });
  }
  return null;
}

/** Results and review (gates GF2-14..17, GF2-20): only what the backend returned for a submitted attempt. */
export function ReviewPage({ attemptId }: { attemptId: string }) {
  if (!CANONICAL_ID.test(attemptId)) return <ResourceNotFound />;
  return <ReviewLoader attemptId={attemptId} />;
}

function ReviewLoader({ attemptId }: { attemptId: string }) {
  const attempt = useAttempt(attemptId);
  const submitted = attempt.data?.status === "submitted";
  const results = useResults(attemptId, { enabled: submitted });
  const quiz = useQuiz(attempt.data?.quiz_id ?? null);
  const course = useCourse(quiz.data?.course_id ?? "", { enabled: Boolean(quiz.data) });

  if (attempt.isError && attempt.error instanceof ApiError && attempt.error.kind === "not_found") return <ResourceNotFound />;
  if (attempt.isPending) return <div aria-busy="true" role="status" aria-label={PROVISIONAL.loading} className="min-h-[50vh]" />;
  if (attempt.isError) {
    return (
      <div role="alert" className="flex flex-col items-start gap-4 px-4 py-10 lg:px-12">
        <Notice tone="warning" title={PROVISIONAL.loadError} />
        <Button variant="secondary" onClick={() => void attempt.refetch()}>
          {PROVISIONAL.tryAgain}
        </Button>
      </div>
    );
  }
  const quizHref = `/quizzes/${encodeURIComponent(attempt.data.quiz_id)}`;
  if (!submitted) {
    const open = attempt.data.status === "in_progress";
    return (
      <div className="flex flex-col items-start gap-4 px-4 py-10 lg:px-12">
        <h1 className="text-h2 text-fg">{open ? PROVISIONAL.continueQuiz : PROVISIONAL.expiredTitle}</h1>
        <Notice tone="info" title={open ? quizError(new ApiError({ kind: "conflict", status: 409, code: "attempt_not_submitted" })) : PROVISIONAL.expiredBody} />
        <ButtonLink href={open ? attemptHref(attempt.data) : quizHref}>{open ? PROVISIONAL.continueQuiz : PROVISIONAL.backToQuiz}</ButtonLink>
      </div>
    );
  }
  if (results.isPending) return <div aria-busy="true" role="status" aria-label={PROVISIONAL.loading} className="min-h-[50vh]" />;
  if (results.isError) {
    return (
      <div role="alert" className="flex flex-col items-start gap-4 px-4 py-10 lg:px-12">
        <Notice tone="warning" title={quizError(results.error)} />
        <Button variant="secondary" onClick={() => void results.refetch()}>
          {PROVISIONAL.tryAgain}
        </Button>
      </div>
    );
  }
  return <Review key={attemptId} results={results.data} quizTitle={quiz.data?.title ?? ""} courseName={course.data?.name ?? ""} quizHref={quizHref} />;
}

function Review({ results, quizTitle, courseName, quizHref }: { results: AttemptResults; quizTitle: string; courseName: string; quizHref: string }) {
  const router = useRouter();
  const retry = useRetryMissed(results);
  const resume = useStartAttempt(results.quiz_id);
  const retryAfter = useRetryAfter();
  const [problem, setProblem] = useState<unknown>(null);
  const firstWrong = results.questions.find((q) => q.correct !== true)?.question_id ?? null;
  const [open, setOpen] = useState<string | null>(firstWrong);
  const inProgressElsewhere = problem instanceof ApiError && problem.code === "attempt_in_progress";

  return (
    <div className="flex min-h-screen flex-col">
      <QuizBar
        exit={<ButtonLink href={quizHref} variant="secondary">{FIGMA.exitQuiz}</ButtonLink>}
        title={courseName ? FIGMA.quizTitle(courseName) : quizTitle}
        subtitle={quizTitle ? `${quizTitle} · ${FIGMA.answerReview}` : FIGMA.answerReview}
        position={FIGMA.review}
        progress={100}
        progressLabel={FIGMA.answerReview}
      />
      <div className="mx-auto flex w-full max-w-[720px] flex-col gap-6 px-4 py-8 lg:py-12">
        <h1 className="sr-only">{FIGMA.answerReview}</h1>
        <section aria-labelledby="result-summary" className="flex flex-col gap-4 rounded-xl border border-line bg-surface p-6">
          <h2 id="result-summary" className="text-h2 text-fg">
            {FIGMA.correctOf(results.score, results.max_score)}
          </h2>
          <p className="text-body text-fg-secondary">{PROVISIONAL.percent(results.percent)}</p>
          {results.topics.length ? (
            <div className="flex flex-col gap-1">
              <p className="text-caption-strong text-fg-secondary">{PROVISIONAL.topics}</p>
              <ul className="flex flex-col">
                {results.topics.map((t) => (
                  <li key={t.topic} className="flex justify-between gap-4 border-b border-line py-2 text-body-sm">
                    <span className="min-w-0 break-words text-fg">{t.topic}</span>
                    <span className="shrink-0 text-fg-secondary">{PROVISIONAL.topicScore(t.score, t.max_score)}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          <div role="alert" className="empty:sr-only">
            {problem ? <Notice tone="warning" title={quizError(problem)} /> : null}
          </div>
          <div className="flex flex-wrap gap-3">
            {results.score < results.max_score && !inProgressElsewhere ? (
              <Button
                variant="secondary"
                loading={retry.isPending}
                disabled={retryAfter.blocked}
                onClick={() =>
                  !retry.isPending &&
                  retry.mutate(undefined, {
                    onSuccess: (attempt) => router.push(attemptHref(attempt)),
                    onError: (error) => {
                      retryAfter.note(error);
                      setProblem(error);
                    },
                  })
                }
              >
                {FIGMA.retryWrong}
              </Button>
            ) : null}
            {inProgressElsewhere ? (
              <Button
                loading={resume.isPending}
                onClick={() => !resume.isPending && resume.mutate(undefined, { onSuccess: (attempt) => router.push(attemptHref(attempt)), onError: setProblem })}
              >
                {PROVISIONAL.continueInProgress}
              </Button>
            ) : null}
          </div>
        </section>

        <ol className="flex flex-col gap-3">
          {results.questions.map((q) => (
            <li key={q.question_id}>
              <QuestionReview result={q} total={results.max_score} expanded={open === q.question_id} onToggle={() => setOpen(open === q.question_id ? null : q.question_id)} />
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

function QuestionReview({ result, total, expanded, onToggle }: { result: ResultQuestion; total: number; expanded: boolean; onToggle: () => void }) {
  const bodyId = useId();
  const verdict = verdictOf(result);
  const rows = reviewRows(result);
  return (
    <section className="rounded-xl border border-line bg-surface" data-result={result.position}>
      <h2 className="m-0">
        <button type="button" aria-expanded={expanded} aria-controls={bodyId} onClick={onToggle} className="flex min-h-[58px] w-full items-center gap-3 rounded-xl px-6 py-3 text-left hover:bg-subtle">
          <Tag tone={verdict.tone}>{verdict.label}</Tag>
          <span className="min-w-0 flex-1 text-label break-words text-fg">{`${FIGMA.questionOf(result.position, total)} · ${result.stem}`}</span>
          <Icon name={expanded ? "chevronDown" : "chevronRight"} size={20} />
        </button>
      </h2>
      <div id={bodyId} hidden={!expanded} className="flex flex-col gap-4 px-6 pb-6">
        <p className="text-title break-words text-fg">{result.stem}</p>
        {rows ? (
          <div className="flex flex-col gap-3">
            {rows.map((row, i) => (
              <AnswerReviewRow key={i} {...row} />
            ))}
          </div>
        ) : (
          <Notice tone="neutral" title={PROVISIONAL.noVerdict} />
        )}
        {result.rationale || result.rationale_chosen ? (
          <div className="flex flex-col gap-2 rounded-md bg-subtle p-4">
            {result.rationale ? (
              <>
                <p className="text-caption-strong text-fg-secondary">{FIGMA.why}</p>
                <p className="text-body break-words whitespace-pre-line text-fg">{result.rationale}</p>
              </>
            ) : null}
            {result.rationale_chosen ? (
              <>
                <p className="text-caption-strong text-fg-secondary">{PROVISIONAL.aboutYourAnswer}</p>
                <p className="text-body break-words whitespace-pre-line text-fg">{result.rationale_chosen}</p>
              </>
            ) : null}
            <p className="text-caption text-fg-secondary">{PROVISIONAL.aiWritten}</p>
          </div>
        ) : null}
        <div className="flex flex-col gap-2">
          <p className="text-caption-strong text-fg-secondary">{PROVISIONAL.evidence}</p>
          <SourceCard fileName={result.citation?.file_name ?? ""} location={result.citation?.citation_label ?? ""} passage={result.evidence} />
        </div>
      </div>
    </section>
  );
}
