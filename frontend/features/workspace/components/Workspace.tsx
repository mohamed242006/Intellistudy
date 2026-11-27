"use client";

import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Button, ButtonLink } from "@/design-system/components/Button";
import { Checkbox } from "@/design-system/components/Checkbox";
import { Notice } from "@/design-system/components/Notice";
import { Tag, type TagTone } from "@/design-system/components/Tag";
import { useToast } from "@/design-system/components/Toast";
import { Breadcrumb } from "@/design-system/compositions/Breadcrumb";
import { Icon } from "@/design-system/icons/Icon";
import type { IconName } from "@/design-system/icons/placeholders";
import { CourseFormModal } from "@/features/courses/components/CourseFormModal";
import { CourseNotFound } from "@/features/courses/components/CourseNotFound";
import { DeleteCourseModal } from "@/features/courses/components/DeleteCourseModal";
import { forgetCourse, useCourse } from "@/features/courses/hooks";
import { FIGMA as COURSE_FIGMA, PROVISIONAL as COURSE_COPY } from "@/features/courses/strings";
import { DeleteDocumentModal } from "@/features/documents/components/DeleteDocumentModal";
import { FileDetails } from "@/features/documents/components/FileDetails";
import { handOff } from "@/features/documents/handoff";
import { useDocument, useDocuments, useDownloadDocument, useRetryDocument } from "@/features/documents/hooks";
import { documentActionError } from "@/features/documents/messages";
import { allState, fileKind, prune, selectAll, splitName, toggle } from "@/features/documents/selection";
import { documentView, summarise } from "@/features/documents/status";
import { FIGMA, PROVISIONAL } from "@/features/documents/strings";
import { QuizStatusTag } from "@/features/quiz/components/QuizListPage";
import { useQuizzes } from "@/features/quiz/hooks";
import { useCourseSummaries, useCreateSummary, useRequestSummary, useSummary, singleSummaryHref } from "@/features/summary/hooks";
import { generationFailure, summaryLoadProblem, summaryRequestError } from "@/features/summary/messages";
import { ApiError } from "@/lib/api/errors";
import type { DocumentOut } from "@/lib/api/types";
import { relativeTime } from "@/lib/format/format";
import { useNow } from "@/lib/format/use-now";
import { WORKSPACE } from "../strings";

const TAG_TONE: Record<string, TagTone> = { extracting: "accent", indexed: "success", failed: "danger", unsupported: "danger", empty: "danger" };
const FILTER_FROM = 7;

/**
 * Course Workspace: the place to pick materials and decide what to do with them.
 * - Materials (left): every file with a real checkbox (ready files only), Select all (tri-state), Clear, the count.
 *   Clicking a file's name PREVIEWS it (left accent bar; drives the details panel); ticking its box CHECKS it for batch
 *   actions (accent fill). The two states are independent and look different.
 * - Focus card (centre): with nothing checked, a study overview from real data (counts, recent combined summaries and
 *   quizzes); with files checked, the selection with its actions. On narrow screens the actions sit in a bottom bar.
 * - Details (right): the previewed file, with its summary in its real state (create / processing / retry / open).
 */
export function Workspace({ courseId }: { courseId: string }) {
  const router = useRouter();
  const params = useSearchParams();
  const toast = useToast();
  const now = useNow();
  const client = useQueryClient();
  const [deleted, setDeleted] = useState(false);
  const course = useCourse(courseId, { enabled: !deleted });
  const documents = useDocuments(courseId, { poll: true, enabled: !deleted });
  const retry = useRetryDocument(courseId);
  const download = useDownloadDocument();
  const combined = useCourseSummaries(courseId, { enabled: course.isSuccess && !deleted });
  const quizzes = useQuizzes(courseId, { enabled: course.isSuccess && !deleted });
  const createSummary = useCreateSummary(courseId);
  const [renaming, setRenaming] = useState(false);
  const [deletingCourse, setDeletingCourse] = useState(false);
  const [deletingDoc, setDeletingDoc] = useState<DocumentOut | null>(null);
  const [checked, setChecked] = useState<string[]>([]);
  const [filter, setFilter] = useState("");

  // After deletion this page stops observing the course, then drops its cache while navigating away (GF0B-13).
  useEffect(() => {
    if (deleted) forgetCourse(client, courseId);
  }, [deleted, client, courseId]);

  // Checked files that are deleted or stop being ready leave the selection.
  const docs = documents.documents;
  const { kept: selection, dropped } = prune(checked, docs);
  useEffect(() => {
    if (dropped.length) setChecked((current) => prune(current, docs).kept);
  }, [dropped.length, docs]);

  const requested = params.get("file");
  const inList = requested ? docs.find((doc) => doc.id === requested) : undefined;
  const single = useDocument(requested, Boolean(requested) && documents.isSuccess && !inList);
  const fetched = single.data?.course_id === courseId ? single.data : undefined; // a file of another course is not shown here
  const previewed: DocumentOut | undefined = inList ?? fetched ?? (requested ? undefined : docs[0]);
  const shown = useMemo(() => {
    const term = filter.trim().toLowerCase();
    return term ? docs.filter((d) => d.file_name.toLowerCase().includes(term)) : docs;
  }, [docs, filter]);

  if (course.isError && course.error instanceof ApiError && course.error.kind === "not_found") return <CourseNotFound />;
  if (course.isPending) return <WorkspaceSkeleton />;
  if (course.isError) {
    return (
      <div role="alert" className="flex flex-col items-start gap-4 px-4 py-10 lg:px-12">
        <Notice tone="warning" title={COURSE_COPY.loadError} body={COURSE_COPY.loadErrorBody} />
        <Button variant="secondary" onClick={() => void course.refetch()}>
          {COURSE_COPY.tryAgain}
        </Button>
      </div>
    );
  }

  const data = course.data;
  const summary = summarise(docs, documents.complete);
  const base = `/courses/${encodeURIComponent(courseId)}`;
  const uploadHref = `${base}/upload`;
  const fileHref = (id: string) => `${base}?file=${encodeURIComponent(id)}`;
  const runRetry = (doc: DocumentOut) => {
    if (retry.isPending) return;
    retry.mutate(doc.id, { onError: (e) => toast(documentActionError(e), "warning") });
  };
  const state = allState(selection, docs);
  const checkedDocs = selection.map((id) => docs.find((d) => d.id === id)!).filter(Boolean);

  const actions = {
    summary: () => {
      if (createSummary.isPending || selection.length === 0) return;
      createSummary.mutate(selection, {
        onSuccess: (href) => router.push(href),
        onError: (error) => toast(summaryRequestError(error), "warning"),
      });
    },
    quiz: () => {
      handOff(courseId, "quiz", selection);
      router.push(`${base}/quizzes?from=workspace`);
    },
    ask: () => {
      handOff(courseId, "chat", selection);
      router.push(`${base}/chat?from=workspace`);
    },
    clear: () => setChecked([]),
  };

  return (
    <div className="mx-auto grid w-full max-w-[1680px] grid-cols-1 gap-4 px-3 pt-4 pb-32 sm:px-4 md:gap-5 md:px-6 lg:grid-cols-[320px_minmax(0,1fr)] lg:pb-8 xl:grid-cols-[320px_minmax(0,1fr)_340px] xl:gap-6 xl:pt-6">
      {/* Course header */}
      <header className="motion-enter flex flex-col gap-3 lg:col-span-2 xl:col-span-3">
        <Breadcrumb items={[{ label: COURSE_FIGMA.courses, href: "/#courses" }, { label: data.name }]} />
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="flex min-w-0 flex-col gap-1">
            <p className="text-caption-strong text-accent-fg">{COURSE_FIGMA.courses.toUpperCase()}</p>
            <h1 className="min-w-0 text-h1 wrap-anywhere text-fg">{data.name}</h1>
            {data.description ? <p className="max-w-[72ch] text-body wrap-anywhere text-fg-secondary">{data.description}</p> : null}
          </div>
          <div role="group" aria-label={WORKSPACE.courseActions} className="flex flex-wrap items-center gap-2">
            <ButtonLink href={`${base}/chat`} leadingIcon={<Icon name="message" size={16} />}>
              {WORKSPACE.ask}
            </ButtonLink>
            <Button variant="ghost" onClick={() => setRenaming(true)}>
              {COURSE_COPY.rename}
            </Button>
            <Button variant="ghost" onClick={() => setDeletingCourse(true)}>
              {COURSE_FIGMA.deleteCourse}
            </Button>
          </div>
        </div>
      </header>

      {/* Materials */}
      <section
        aria-labelledby="materials-heading"
        className="motion-enter flex min-w-0 flex-col gap-3 self-start rounded-xl border border-line bg-surface p-3 shadow-sm sm:p-4 lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:overflow-y-auto"
      >
        <div className="flex items-center justify-between gap-2 px-1">
          <h2 id="materials-heading" className="text-title text-fg">
            {FIGMA.materials}
          </h2>
          {documents.isSuccess ? (
            <span className="text-caption text-fg-secondary">
              {PROVISIONAL.fileCount(summary.total)}
              {summary.complete ? "" : "+"}
            </span>
          ) : null}
        </div>
        <ButtonLink href={uploadHref} variant="secondary" fullWidth leadingIcon={<Icon name="plus" size={16} />}>
          {FIGMA.addFiles}
        </ButtonLink>
        {summary.indexed > 0 ? (
          <div className="flex items-center gap-1 rounded-lg bg-subtle pr-2">
            <Checkbox
              checked={state === "all"}
              indeterminate={state === "some"}
              onChange={(on) => setChecked(on ? selectAll(docs) : [])}
              label={WORKSPACE.selectAll}
              testId="select-all"
            />
            <span className="flex min-w-0 flex-1 flex-col py-1">
              <span aria-hidden="true" className="text-label text-fg">
                {WORKSPACE.selectAll}
              </span>
              <span aria-live="polite" data-testid="workspace-count" className="text-caption text-fg-secondary tabular-nums">
                {WORKSPACE.ofSelected(selection.length, summary.indexed)}
              </span>
            </span>
            {selection.length ? (
              <button type="button" onClick={actions.clear} className="motion-enter-fast min-h-11 rounded-md px-2 text-label text-accent-fg hover:bg-accent-subtle">
                {WORKSPACE.clear}
              </button>
            ) : null}
          </div>
        ) : null}
        {docs.length >= FILTER_FROM ? (
          <label className="flex flex-col gap-1">
            <span className="sr-only">{WORKSPACE.filter}</span>
            <input
              type="search"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder={WORKSPACE.filter}
              className="h-11 rounded-md border border-line-strong bg-surface px-3 text-body text-fg placeholder:text-fg-tertiary"
            />
          </label>
        ) : null}
        {documents.isPending ? (
          <div aria-busy="true" role="status" aria-label={FIGMA.materials} className="flex flex-col gap-2">
            {[0, 1, 2].map((i) => (
              <span key={i} className="motion-pulse h-14 rounded-lg bg-subtle" />
            ))}
          </div>
        ) : null}
        <ul className="motion-stagger flex flex-col gap-1">
          {shown.map((doc) => (
            <MaterialRow
              key={doc.id}
              doc={doc}
              now={now}
              active={previewed?.id === doc.id}
              checked={selection.includes(doc.id)}
              href={fileHref(doc.id)}
              onCheck={(on) => setChecked(toggle(selection, doc.id, on, docs))}
              onRetry={() => runRetry(doc)}
              retrying={retry.isPending}
            />
          ))}
        </ul>
        {filter && shown.length === 0 ? <p className="px-1 text-body-sm text-fg-secondary">{WORKSPACE.noMatch}</p> : null}
        {documents.hasNextPage ? (
          <Button variant="secondary" loading={documents.isFetchingNextPage} onClick={() => void documents.fetchNextPage()}>
            {PROVISIONAL.showMoreFiles}
          </Button>
        ) : null}
      </section>

      {/* Centre */}
      <div className="flex min-w-0 flex-col gap-4 md:gap-5">
        {documents.isError && docs.length === 0 ? (
          <div role="alert" className="flex flex-col items-start gap-4">
            <Notice tone="warning" title={PROVISIONAL.documentsError} />
            <Button variant="secondary" onClick={() => void documents.refetch()}>
              {PROVISIONAL.tryAgain}
            </Button>
          </div>
        ) : null}
        {documents.pollingStopped ? (
          <div role="alert" className="flex flex-col items-start gap-4">
            <Notice tone="warning" title={PROVISIONAL.pollingStopped} body={PROVISIONAL.pollingStoppedBody} />
            <Button variant="secondary" onClick={documents.resumePolling}>
              {PROVISIONAL.tryAgain}
            </Button>
          </div>
        ) : null}

        {selection.length ? (
          <section
            key="selection"
            aria-labelledby="selection-heading"
            data-testid="selection-card"
            className="motion-enter-fast flex flex-col gap-4 rounded-xl border border-accent-subtle-border bg-surface p-4 shadow-md sm:p-6"
          >
            <div className="flex flex-wrap items-center gap-3">
              <span className="flex size-10 items-center justify-center rounded-full bg-accent-subtle text-accent-fg">
                <Icon name="layers" size={20} />
              </span>
              <h2 id="selection-heading" className="text-h3 text-fg">
                {WORKSPACE.selectionTitle(selection.length)}
              </h2>
            </div>
            <ul className="flex flex-wrap gap-2" aria-label={WORKSPACE.selected(selection.length)}>
              {checkedDocs.map((doc) => (
                <li key={doc.id} className="motion-enter-fast min-w-0 max-w-full">
                  <span className="flex min-h-11 max-w-full items-center gap-1 rounded-full border border-accent-subtle-border bg-accent-subtle py-1 pr-1 pl-3 text-label text-accent-fg">
                    <Icon name="file" size={16} />
                    <FileName name={doc.file_name} />
                    <button
                      type="button"
                      aria-label={WORKSPACE.remove(doc.file_name)}
                      onClick={() => setChecked(toggle(selection, doc.id, false, docs))}
                      className="flex size-9 shrink-0 items-center justify-center rounded-full hover:bg-surface"
                    >
                      <Icon name="x" size={16} />
                    </button>
                  </span>
                </li>
              ))}
            </ul>
            <p className="max-w-[70ch] text-body-sm text-fg-secondary">{WORKSPACE.selectionExplain(selection.length)}</p>
            <div className="hidden flex-wrap gap-3 lg:flex">
              <SelectionActions count={selection.length} creating={createSummary.isPending} actions={actions} />
            </div>
          </section>
        ) : (
          <Overview
            key="overview"
            total={summary.total}
            indexed={summary.indexed}
            processing={summary.processing}
            loaded={documents.isSuccess}
            uploadHref={uploadHref}
            base={base}
            combined={combined.data?.items ?? null}
            quizzes={quizzes.data?.pages.flatMap((p) => p.items) ?? null}
            now={now}
          />
        )}
      </div>

      {/* Details of the previewed file */}
      <aside
        aria-label={FIGMA.selectedFile}
        className="min-w-0 self-start rounded-xl border border-line bg-surface p-4 shadow-sm sm:p-6 lg:col-start-2 xl:sticky xl:top-4 xl:col-start-3 xl:row-start-2"
      >
        {previewed ? (
          <FileDetails
            key={previewed.id}
            document={previewed}
            now={now}
            downloading={download.isPending && download.variables?.id === previewed.id}
            onDownload={() => {
              if (download.isPending) return;
              download.mutate(previewed, { onError: (e) => toast(e instanceof ApiError ? documentActionError(e) : PROVISIONAL.downloadFailed, "warning") });
            }}
            retrying={retry.isPending}
            onRetry={() => runRetry(previewed)}
            onDelete={() => setDeletingDoc(previewed)}
            summaryAction={<SummaryAction courseId={courseId} documentId={previewed.id} enabled={previewed.status === "ready"} />}
            quizHref={`${base}/quizzes?document=${encodeURIComponent(previewed.id)}`}
          />
        ) : documents.isPending ? (
          <div aria-hidden="true" className="flex flex-col gap-3">
            <span className="motion-pulse h-4 w-24 rounded-sm bg-subtle" />
            <span className="motion-pulse h-7 w-3/4 rounded-sm bg-subtle" />
            <span className="motion-pulse h-24 rounded-md bg-subtle" />
          </div>
        ) : (
          <p className="text-body-sm text-fg-secondary">{requested ? PROVISIONAL.notFound : summary.total ? PROVISIONAL.selectHint : WORKSPACE.startBody}</p>
        )}
      </aside>

      {/* Narrow screens: the checked-files actions in a sticky bottom bar (the focus card holds them from 1024 px) */}
      <div
        className="is-batch-bar fixed inset-x-0 bottom-0 z-40 border-t border-line bg-raised px-3 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] shadow-lg lg:hidden"
        data-open={selection.length > 0 ? "true" : "false"}
        aria-hidden={selection.length === 0 || undefined}
        inert={selection.length === 0 || undefined}
        data-testid="batch-bar"
      >
        <div className="mx-auto flex max-w-[720px] flex-col gap-2">
          <p className="text-label text-fg">{WORKSPACE.selected(selection.length)}</p>
          <div className="flex flex-wrap gap-2">
            <SelectionActions count={selection.length} creating={createSummary.isPending} actions={actions} compact />
          </div>
        </div>
      </div>

      <CourseFormModal
        mode="rename"
        course={data}
        open={renaming}
        onClose={() => setRenaming(false)}
        onSaved={() => {
          setRenaming(false);
          toast(COURSE_COPY.courseRenamed, "success");
        }}
      />
      <DeleteCourseModal
        open={deletingCourse}
        courseId={courseId}
        fileCount={documents.complete ? summary.total : null}
        onClose={() => setDeletingCourse(false)}
        onDeleted={() => {
          setDeletingCourse(false);
          setDeleted(true);
          toast(COURSE_COPY.courseDeleted, "success");
          router.replace("/");
        }}
      />
      <DeleteDocumentModal
        courseId={courseId}
        document={deletingDoc}
        onClose={() => setDeletingDoc(null)}
        onDeleted={(id) => {
          setChecked((current) => current.filter((c) => c !== id));
          if (requested === id) router.replace(base, { scroll: false });
        }}
      />
    </div>
  );
}

function pageCount(n: number, type: string): string {
  const unit = type === "pptx" ? "slide" : "page";
  return `${n} ${n === 1 ? unit : `${unit}s`}`;
}

/** A file name whose stem truncates while the extension stays visible; the full name is the title. */
function FileName({ name }: { name: string }) {
  const { stem, ext } = splitName(name);
  return (
    <span className="flex min-w-0" title={name}>
      <span className="truncate">{stem}</span>
      <span className="shrink-0">{ext}</span>
    </span>
  );
}

function MaterialRow({ doc, now, active, checked, href, onCheck, onRetry, retrying }: {
  doc: DocumentOut;
  now: Date;
  active: boolean;
  checked: boolean;
  href: string;
  onCheck: (on: boolean) => void;
  onRetry: () => void;
  retrying: boolean;
}) {
  const view = documentView(doc, now);
  const ready = doc.status === "ready";
  const reasonId = `why-${doc.id}`;
  return (
    <li
      data-active={active || undefined}
      data-checked={checked || undefined}
      className={`relative flex min-w-0 flex-col rounded-lg border transition-[background-color,border-color,box-shadow] duration-150 ${
        checked ? "border-accent bg-accent-subtle shadow-sm" : active ? "border-line-strong bg-subtle" : "border-transparent hover:bg-subtle"
      }`}
    >
      {active ? <span aria-hidden="true" className="motion-enter-fast absolute top-2 bottom-2 left-0 w-1 rounded-full bg-accent" /> : null}
      <div className="flex min-w-0 items-center">
        <Checkbox checked={checked} disabled={!ready} onChange={onCheck} label={WORKSPACE.check(doc.file_name)} describedBy={ready ? undefined : reasonId} />
        <Link
          href={href}
          scroll={false}
          aria-current={active ? "true" : undefined}
          className="flex min-w-0 flex-1 flex-col gap-1 rounded-md py-2 pr-2"
        >
          {/* the accessible name starts with "Preview" and then contains all the visible text (WCAG 2.5.3) */}
          {/* one text node for the name (a split stem/extension would be read as two words); the type is in the meta */}
          <span className="min-w-0 truncate text-label text-fg" title={doc.file_name}>
            <span className="sr-only">{WORKSPACE.previewPrefix}</span>
            {doc.file_name}
          </span>
          <span className="flex flex-wrap items-center gap-2">
            <Tag tone={TAG_TONE[view.status] ?? "neutral"}>{view.tag}</Tag>
            <span className="text-caption text-fg-secondary">
              {[fileKind(doc), doc.page_count ? pageCount(doc.page_count, doc.file_type) : null].filter(Boolean).join(" · ")}
            </span>
          </span>
        </Link>
      </div>
      {!ready ? (
        <p id={reasonId} className="sr-only">
          {WORKSPACE.notSelectable(view.tag)}
        </p>
      ) : null}
      {view.canRetry ? (
        <button
          type="button"
          onClick={onRetry}
          disabled={retrying}
          aria-label={PROVISIONAL.retryLabel(doc.file_name)}
          className="mb-1 ml-11 min-h-11 self-start rounded-md px-1 text-label text-fg-link hover:underline disabled:text-disabled-fg"
        >
          {FIGMA.retry}
        </button>
      ) : null}
    </li>
  );
}

function SelectionActions({ count, creating, actions, compact = false }: {
  count: number;
  creating: boolean;
  actions: { summary: () => void; quiz: () => void; ask: () => void; clear: () => void };
  compact?: boolean;
}) {
  return (
    <>
      <Button loading={creating} onClick={actions.summary} leadingIcon={<Icon name="book" size={16} />}>
        {creating ? WORKSPACE.creatingSummary : WORKSPACE.createSummary(count)}
      </Button>
      <Button variant="secondary" onClick={actions.quiz} leadingIcon={<Icon name="quiz" size={16} />}>
        {WORKSPACE.createQuiz}
      </Button>
      <Button variant="secondary" onClick={actions.ask} leadingIcon={<Icon name="message" size={16} />}>
        {compact ? "Ask" : WORKSPACE.askSelected}
      </Button>
      <Button variant="ghost" onClick={actions.clear} aria-label={WORKSPACE.clearSelection}>
        {compact ? WORKSPACE.clear : WORKSPACE.clearSelection}
      </Button>
    </>
  );
}

/** The previewed file's summary, in its real state: never "Open summary" unless a summary exists. */
function SummaryAction({ courseId, documentId, enabled }: { courseId: string; documentId: string; enabled: boolean }) {
  const router = useRouter();
  const toast = useToast();
  const summary = useSummary(documentId, { enabled });
  const request = useRequestSummary(documentId);
  const href = singleSummaryHref(courseId, documentId);
  const create = () => {
    if (request.isPending) return;
    request.mutate(false, {
      onSuccess: () => router.push(href),
      onError: (error) => toast(summaryRequestError(error), "warning"),
    });
  };
  if (summary.isPending) {
    return (
      <Button fullWidth disabled loading>
        {WORKSPACE.summaryChecking}
      </Button>
    );
  }
  if (summary.isError) {
    const problem = summaryLoadProblem(summary.error);
    return (
      <div className="flex flex-col gap-2">
        <Notice tone="warning" title={problem.title} body={problem.body} />
        <Button variant="secondary" fullWidth onClick={() => void summary.refetch()}>
          {PROVISIONAL.tryAgain}
        </Button>
      </div>
    );
  }
  const data = summary.data;
  if (!data) {
    return (
      <Button fullWidth loading={request.isPending} onClick={create} leadingIcon={<Icon name="book" size={16} />}>
        {WORKSPACE.summaryCreate}
      </Button>
    );
  }
  if (data.status === "generating") {
    return (
      <div className="flex flex-col gap-2">
        <Button fullWidth disabled loading>
          {WORKSPACE.summaryProcessing}
        </Button>
        <Link href={href} className="self-start rounded-md px-1 text-label text-fg-link hover:underline">
          {WORKSPACE.summaryView}
        </Link>
      </div>
    );
  }
  if (data.status === "failed") {
    return (
      <div className="flex flex-col gap-2">
        <p className="text-body-sm text-danger-fg">{generationFailure(data.error_code)}</p>
        <Button fullWidth loading={request.isPending} onClick={create} leadingIcon={<Icon name="retry" size={16} />}>
          {WORKSPACE.summaryRetry}
        </Button>
      </div>
    );
  }
  return (
    <ButtonLink href={href} fullWidth leadingIcon={<Icon name="book" size={16} />}>
      {WORKSPACE.summaryOpen}
    </ButtonLink>
  );
}

type CombinedItem = { id: string; title: string; status: string; source_documents: unknown[]; created_at: string };
type QuizItem = { id: string; title: string; status: string; question_count: number; created_at: string };

function Stat({ icon, label, value }: { icon: IconName; label: string; value: string }) {
  return (
    <div className="flex min-w-0 items-center gap-3 rounded-lg border border-line bg-canvas/60 p-3">
      <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-accent-subtle text-accent-fg">
        <Icon name={icon} size={18} />
      </span>
      <span className="flex min-w-0 flex-col">
        <span className="text-h3 text-fg tabular-nums">{value}</span>
        <span className="text-caption text-fg-secondary">{label}</span>
      </span>
    </div>
  );
}

/** Nothing checked: what this course holds (real counts and recent items only) and how to start. */
function Overview({ total, indexed, processing, loaded, uploadHref, base, combined, quizzes, now }: {
  total: number;
  indexed: number;
  processing: number;
  loaded: boolean;
  uploadHref: string;
  base: string;
  combined: CombinedItem[] | null;
  quizzes: QuizItem[] | null;
  now: Date;
}) {
  if (loaded && total === 0) {
    return (
      <section aria-labelledby="start-heading" className="motion-enter-fast flex flex-col items-center gap-4 rounded-xl border border-dashed border-line-strong bg-surface/80 px-6 py-14 text-center shadow-sm">
        <span className="flex size-14 items-center justify-center rounded-full bg-accent-subtle text-accent-fg">
          <Icon name="upload" size={24} />
        </span>
        <h2 id="start-heading" className="text-h3 text-fg">
          {FIGMA.noMaterialsTitle}
        </h2>
        <p className="max-w-[52ch] text-body text-fg-secondary">{FIGMA.noMaterialsBody}</p>
        <ButtonLink href={uploadHref}>{FIGMA.uploadFiles}</ButtonLink>
      </section>
    );
  }
  return (
    <section aria-labelledby="overview-heading" className="motion-enter-fast flex flex-col gap-5 rounded-xl border border-line bg-surface p-4 shadow-sm sm:p-6">
      <div className="flex flex-col gap-1">
        <h2 id="overview-heading" className="text-h3 text-fg">
          {WORKSPACE.overviewTitle}
        </h2>
        <p className="max-w-[70ch] text-body-sm text-fg-secondary">{indexed > 0 ? WORKSPACE.overviewBody : WORKSPACE.overviewNoReady}</p>
      </div>
      {loaded ? (
        <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
          <Stat icon="file" label={WORKSPACE.stats.files} value={String(total)} />
          <Stat icon="checkCircle" label={processing ? `${WORKSPACE.stats.ready} · ${processing} processing` : WORKSPACE.stats.ready} value={String(indexed)} />
          <Stat icon="layers" label={WORKSPACE.stats.summaries} value={combined ? String(combined.length) : "–"} />
          <Stat icon="quiz" label={WORKSPACE.stats.quizzes} value={quizzes ? String(quizzes.length) : "–"} />
        </div>
      ) : null}
      <div className="grid gap-5 xl:grid-cols-2">
        <Recent
          title={WORKSPACE.recentSummaries}
          more={{ href: `${base}/summaries`, label: WORKSPACE.allSummaries }}
          empty={WORKSPACE.noSummaries}
          items={combined?.slice(0, 3).map((s) => ({ id: s.id, href: `/summaries/${encodeURIComponent(s.id)}`, title: s.title, meta: [`${s.source_documents.length} files`, relativeTime(s.created_at, now)].join(" · "), status: s.status })) ?? null}
        />
        <Recent
          title={WORKSPACE.recentQuizzes}
          more={{ href: `${base}/quizzes`, label: WORKSPACE.allQuizzes }}
          empty={WORKSPACE.noQuizzes}
          quiz
          items={quizzes?.slice(0, 3).map((q) => ({ id: q.id, href: `/quizzes/${encodeURIComponent(q.id)}`, title: q.title, meta: [q.status === "ready" ? `${q.question_count} questions` : null, relativeTime(q.created_at, now)].filter(Boolean).join(" · "), status: q.status })) ?? null}
        />
      </div>
    </section>
  );
}

function Recent({ title, more, empty, items, quiz = false }: {
  title: string;
  more: { href: string; label: string };
  empty: string;
  items: { id: string; href: string; title: string; meta: string; status: string }[] | null;
  quiz?: boolean;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-caption-strong text-fg-secondary">{title.toUpperCase()}</h3>
        <Link href={more.href} className="min-h-11 content-center rounded-md px-2 text-label text-fg-link hover:underline">
          {more.label}
        </Link>
      </div>
      {items === null ? <span className="motion-pulse h-16 rounded-lg bg-subtle" aria-hidden="true" /> : null}
      {items && items.length === 0 ? <p className="rounded-lg bg-subtle px-3 py-3 text-body-sm text-fg-secondary">{empty}</p> : null}
      {items && items.length ? (
        <ul className="motion-stagger flex flex-col gap-2">
          {items.map((item) => (
            <li key={item.id}>
              <Link href={item.href} className="flex min-w-0 flex-col gap-1 rounded-lg border border-line bg-surface px-3 py-2 transition-shadow hover:border-line-strong hover:shadow-md">
                <span className="flex min-w-0 items-center gap-2">
                  <span className="min-w-0 flex-1 truncate text-label text-fg" title={item.title}>
                    {item.title}
                  </span>
                  {quiz ? <QuizStatusTag status={item.status} /> : <Tag tone={item.status === "ready" ? "success" : item.status === "failed" ? "danger" : "accent"}>{item.status === "ready" ? "Ready" : item.status === "failed" ? "Failed" : "Generating"}</Tag>}
                </span>
                <span className="text-caption text-fg-secondary">{item.meta}</span>
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function WorkspaceSkeleton() {
  return (
    <div aria-busy="true" role="status" aria-label={COURSE_COPY.loadingCourses} className="mx-auto grid w-full max-w-[1680px] gap-4 px-4 py-6 lg:grid-cols-[320px_minmax(0,1fr)]">
      <span className="motion-pulse h-10 w-1/2 rounded-md bg-subtle lg:col-span-2" />
      <span className="motion-pulse h-72 rounded-xl bg-subtle" />
      <span className="motion-pulse h-72 rounded-xl bg-subtle" />
    </div>
  );
}
