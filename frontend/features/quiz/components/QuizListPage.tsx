"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useId, useState, type FormEvent } from "react";
import { Button } from "@/design-system/components/Button";
import { EmptyState } from "@/design-system/components/EmptyState";
import { Input } from "@/design-system/components/Input";
import { Notice } from "@/design-system/components/Notice";
import { Tag, type TagTone } from "@/design-system/components/Tag";
import { Breadcrumb } from "@/design-system/compositions/Breadcrumb";
import { CourseNotFound } from "@/features/courses/components/CourseNotFound";
import { useCourse } from "@/features/courses/hooks";
import { FIGMA as COURSE_FIGMA } from "@/features/courses/strings";
import { DocumentPicker } from "@/features/documents/components/DocumentPicker";
import { useDocuments } from "@/features/documents/hooks";
import { SELECTION_COPY, prune } from "@/features/documents/selection";
import { ApiError } from "@/lib/api/errors";
import type { DocumentOut, QuizOut } from "@/lib/api/types";
import { relativeTime } from "@/lib/format/format";
import { useNow } from "@/lib/format/use-now";
import { useRetryAfter } from "@/lib/hooks/use-retry-after";
import type { QuizRequest } from "../api";
import { useCreateQuiz, useQuizzes } from "../hooks";
import { quizError } from "../messages";
import { PROVISIONAL } from "../strings";

export const MIN_QUESTIONS = 5;
export const MAX_QUESTIONS = 30;
export const MAX_QUIZ_DOCUMENTS = 20;
export const TITLE_MAX = 200;

/** `documents` is the explicit selection (DocumentPicker); "Select all ready files" sends every ready id explicitly. */
export type QuizForm = { title: string; count: string; mcq: boolean; trueFalse: boolean; documents: string[] };
export type QuizFormErrors = Partial<Record<"title" | "count" | "types" | "files", string>>;

/** Client checks mirroring QuizCreate (backend/app/api/v1/generation.py); the backend stays authoritative (GF2-03). */
export function validateQuizForm(form: QuizForm, ready: readonly Pick<DocumentOut, "id">[]): { request: QuizRequest | null; errors: QuizFormErrors } {
  const errors: QuizFormErrors = {};
  const title = form.title.trim();
  if (Array.from(title).length > TITLE_MAX) errors.title = PROVISIONAL.errors.title;
  const count = /^\d{1,2}$/.test(form.count.trim()) ? Number(form.count.trim()) : NaN;
  if (!(count >= MIN_QUESTIONS && count <= MAX_QUESTIONS)) errors.count = PROVISIONAL.errors.count;
  const types = [...(form.mcq ? (["mcq"] as const) : []), ...(form.trueFalse ? (["true_false"] as const) : [])];
  if (types.length === 0) errors.types = PROVISIONAL.errors.types;
  const readyIds = new Set(ready.map((d) => d.id));
  const documents = [...new Set(form.documents)].filter((id) => readyIds.has(id));
  if (documents.length < 1 || documents.length > MAX_QUIZ_DOCUMENTS) errors.files = PROVISIONAL.errors.files;
  if (Object.keys(errors).length) return { request: null, errors };
  const request: QuizRequest = { question_count: count, question_types: types, document_ids: documents };
  if (title) request.title = title;
  return { request, errors };
}

const STATUS_TONE: Record<string, TagTone> = { generating: "accent", ready: "success", failed: "danger", invalid: "warning" };

export function QuizStatusTag({ status }: { status: string }) {
  return <Tag tone={STATUS_TONE[status] ?? "neutral"}>{PROVISIONAL.status[status] ?? PROVISIONAL.unknownStatus}</Tag>;
}

/** Course quizzes (docs/F2_GATE.md; gates GF2-01..05): the backend's quizzes and the generation form. */
export function QuizListPage({ courseId }: { courseId: string }) {
  const now = useNow();
  const params = useSearchParams();
  const course = useCourse(courseId);
  const quizzes = useQuizzes(courseId, { enabled: course.isSuccess });
  const documents = useDocuments(courseId, { poll: false, enabled: course.isSuccess });

  if (course.isError && course.error instanceof ApiError && course.error.kind === "not_found") return <CourseNotFound />;
  if (course.isPending) return <div aria-busy="true" role="status" aria-label={PROVISIONAL.loading} className="min-h-[50vh]" />;
  if (course.isError) {
    return (
      <div role="alert" className="flex flex-col items-start gap-4 px-4 py-10 lg:px-12">
        <Notice tone="warning" title={PROVISIONAL.loadError} />
        <Button variant="secondary" onClick={() => void course.refetch()}>
          {PROVISIONAL.tryAgain}
        </Button>
      </div>
    );
  }

  const list = quizzes.data?.pages.flatMap((p) => p.items) ?? [];
  const ready = documents.documents.filter((d) => d.status === "ready");
  const preselected = params.get("document");

  return (
    <div className="mx-auto flex w-full max-w-[1080px] flex-col gap-8 px-4 py-6 md:px-8 lg:px-12 lg:pt-8 lg:pb-12">
      <Breadcrumb items={[{ label: COURSE_FIGMA.courses, href: "/#courses" }, { label: course.data.name, href: `/courses/${encodeURIComponent(courseId)}` }, { label: PROVISIONAL.quizzes }]} />
      <h1 className="text-h1 break-words text-fg">{PROVISIONAL.quizzes}</h1>

      <section aria-labelledby="generate-heading" className="flex flex-col gap-4 rounded-xl border border-line bg-surface p-6">
        <h2 id="generate-heading" className="text-h3 text-fg">
          {PROVISIONAL.generateTitle}
        </h2>
        <p className="text-body text-fg-secondary">{PROVISIONAL.generateBody}</p>
        {documents.isPending ? <div aria-busy="true" role="status" aria-label={PROVISIONAL.loading} className="h-10" /> : null}
        {documents.isSuccess && ready.length === 0 ? <Notice tone="info" title={PROVISIONAL.noReadyFiles} /> : null}
        {documents.isSuccess && documents.documents.length > 0 ? (
          <GenerateForm key={preselected ?? "none"} courseId={courseId} all={documents.documents} ready={ready} preselected={preselected && ready.some((d) => d.id === preselected) ? preselected : null} />
        ) : null}
      </section>

      <section aria-labelledby="quizzes-heading" className="flex flex-col gap-4">
        <h2 id="quizzes-heading" className="text-h2 text-fg">
          {PROVISIONAL.quizzes}
        </h2>
        {quizzes.isPending ? <div aria-busy="true" role="status" aria-label={PROVISIONAL.loading} className="h-24" /> : null}
        {quizzes.isError && list.length === 0 ? (
          <div role="alert" className="flex flex-col items-start gap-3">
            <Notice tone="warning" title={PROVISIONAL.loadError} />
            <Button variant="secondary" onClick={() => void quizzes.refetch()}>
              {PROVISIONAL.tryAgain}
            </Button>
          </div>
        ) : null}
        {quizzes.isSuccess && list.length === 0 ? (
          <div className="rounded-xl border border-line bg-surface">
            <EmptyState size="panel" icon="quiz" headingLevel={3} title={PROVISIONAL.emptyTitle} body={PROVISIONAL.emptyBody} />
          </div>
        ) : null}
        <ul className="flex flex-col gap-3">
          {list.map((quiz) => (
            <li key={quiz.id}>
              <QuizRow quiz={quiz} now={now} />
            </li>
          ))}
        </ul>
        {quizzes.hasNextPage ? (
          <div>
            <Button variant="secondary" loading={quizzes.isFetchingNextPage} onClick={() => void quizzes.fetchNextPage()}>
              {PROVISIONAL.showMore}
            </Button>
          </div>
        ) : null}
      </section>
    </div>
  );
}

function QuizRow({ quiz, now }: { quiz: QuizOut; now: Date }) {
  const meta = [quiz.status === "ready" ? PROVISIONAL.questionsCount(quiz.question_count) : null, relativeTime(quiz.created_at, now)].filter(Boolean).join(" · ");
  return (
    <Link href={`/quizzes/${encodeURIComponent(quiz.id)}`} className="flex flex-col gap-2 rounded-xl border border-line bg-surface p-4 hover:border-line-strong hover:shadow-md">
      <span className="flex flex-wrap items-center gap-2">
        <span className="min-w-0 text-title break-words text-fg">{quiz.title}</span>
        <QuizStatusTag status={quiz.status} />
      </span>
      <span className="text-caption text-fg-secondary">{meta}</span>
    </Link>
  );
}

function GenerateForm({ courseId, all, ready, preselected }: { courseId: string; all: DocumentOut[]; ready: DocumentOut[]; preselected: string | null }) {
  const router = useRouter();
  const create = useCreateQuiz(courseId);
  const retryAfter = useRetryAfter();
  const ids = useId();
  const [form, setForm] = useState<QuizForm>({ title: "", count: "10", mcq: true, trueFalse: true, documents: preselected ? [preselected] : [] });
  const [errors, setErrors] = useState<QuizFormErrors>({});
  const [problem, setProblem] = useState<string | null>(null);
  // Files that stop being ready (deleted, reprocessed) leave the selection, and the reader is told.
  const { kept, dropped } = prune(form.documents, all);
  const [notice, setNotice] = useState<string | null>(null);
  useEffect(() => {
    if (dropped.length) {
      setForm((f) => ({ ...f, documents: prune(f.documents, all).kept }));
      setNotice(SELECTION_COPY.dropped(dropped.length));
    }
  }, [dropped.length, all]);
  const selectedCount = kept.length;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (create.isPending || retryAfter.blocked) return;
    const { request, errors: found } = validateQuizForm(form, ready);
    setErrors(found);
    if (!request) return;
    setProblem(null);
    create.mutate(request, {
      onSuccess: (quiz) => router.push(`/quizzes/${encodeURIComponent(quiz.id)}`),
      onError: (error) => {
        retryAfter.note(error); // the selection is kept so the reader can retry
        setProblem(quizError(error));
      },
    });
  };

  return (
    <form noValidate onSubmit={submit} className="flex flex-col gap-5">
      <div role="alert" className="empty:sr-only">
        {problem ? <Notice tone="warning" title={problem} /> : null}
      </div>
      <div className="grid gap-5 md:grid-cols-2">
        <Input label={PROVISIONAL.titleLabel} helper={PROVISIONAL.titleHelper} error={errors.title} value={form.title} maxLength={TITLE_MAX * 2} onChange={(e) => setForm({ ...form, title: e.target.value })} />
        <Input label={PROVISIONAL.countLabel} helper={PROVISIONAL.countHelper} error={errors.count} type="number" inputMode="numeric" min={MIN_QUESTIONS} max={MAX_QUESTIONS} value={form.count} onChange={(e) => setForm({ ...form, count: e.target.value })} />
      </div>
      <fieldset className="flex flex-col gap-2" aria-describedby={errors.types ? `${ids}-types` : undefined}>
        <legend className="mb-1 text-label text-fg">{PROVISIONAL.typesLegend}</legend>
        <div className="flex flex-wrap gap-4">
          {(
            [
              ["mcq", PROVISIONAL.typeMcq],
              ["trueFalse", PROVISIONAL.typeTf],
            ] as const
          ).map(([key, label]) => (
            <label key={key} className="flex min-h-11 cursor-pointer items-center gap-2 text-body text-fg">
              <input type="checkbox" checked={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.checked })} className="size-5 accent-[var(--color-accent)]" />
              {label}
            </label>
          ))}
        </div>
        {errors.types ? (
          <p id={`${ids}-types`} className="text-body-sm text-danger-fg">
            {errors.types}
          </p>
        ) : null}
      </fieldset>
      <div className="flex flex-col gap-2">
        {notice ? <Notice tone="info" title={notice} /> : null}
        <DocumentPicker
          legend={PROVISIONAL.filesLegend}
          documents={all}
          selected={kept}
          disabled={create.isPending}
          hint={selectedCount === 0 ? SELECTION_COPY.quizHint : undefined}
          onChange={(documents) => {
            setNotice(null);
            setForm({ ...form, documents });
          }}
        />
        {errors.files ? (
          <p id={`${ids}-files`} className="text-body-sm text-danger-fg">
            {errors.files}
          </p>
        ) : null}
      </div>
      <div className="sticky bottom-0 -mx-6 flex flex-wrap items-center gap-3 border-t border-line bg-surface px-6 py-4 sm:static sm:mx-0 sm:border-0 sm:p-0">
        <Button type="submit" loading={create.isPending} disabled={retryAfter.blocked || selectedCount === 0}>
          {create.isPending ? SELECTION_COPY.creatingQuiz : SELECTION_COPY.createQuiz(selectedCount)}
        </Button>
        {selectedCount === 0 ? <p className="text-body-sm text-fg-secondary">{SELECTION_COPY.quizHint}</p> : null}
      </div>
    </form>
  );
}
