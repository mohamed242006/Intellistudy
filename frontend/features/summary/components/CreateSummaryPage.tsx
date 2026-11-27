"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { Button } from "@/design-system/components/Button";
import { Notice } from "@/design-system/components/Notice";
import { Tag } from "@/design-system/components/Tag";
import { Breadcrumb } from "@/design-system/compositions/Breadcrumb";
import { CourseNotFound } from "@/features/courses/components/CourseNotFound";
import { useCourse } from "@/features/courses/hooks";
import { FIGMA as COURSE_FIGMA } from "@/features/courses/strings";
import { DocumentPicker } from "@/features/documents/components/DocumentPicker";
import { useDocuments } from "@/features/documents/hooks";
import { MAX_SELECTED_DOCUMENTS, SELECTION_COPY, prune } from "@/features/documents/selection";
import { ApiError } from "@/lib/api/errors";
import type { DocumentOut } from "@/lib/api/types";
import { relativeTime } from "@/lib/format/format";
import { useNow } from "@/lib/format/use-now";
import { useRetryAfter } from "@/lib/hooks/use-retry-after";
import { queryKeys } from "@/lib/query/keys";
import { combinedSummaryHref, useCourseSummaries, useCreateSummary } from "../hooks";
import { summaryRequestError } from "../messages";
import { COMBINED, PROVISIONAL } from "../strings";

export { combinedSummaryHref, singleSummaryHref } from "../hooks";

/**
 * Create a summary from one, several or all ready files (GET /courses/{id}/summaries/new is this page). One file uses
 * that file's own summary (POST /documents/{id}/summary, unchanged); two or more create ONE combined summary
 * (POST /courses/{id}/summaries). `?document=<id>` preselects a file and the reader can add more.
 */
export function CreateSummaryPage({ courseId }: { courseId: string }) {
  const course = useCourse(courseId);
  const documents = useDocuments(courseId, { poll: true, enabled: course.isSuccess });
  const combined = useCourseSummaries(courseId, { enabled: course.isSuccess });
  const params = useSearchParams();
  const now = useNow();

  if (course.isError && course.error instanceof ApiError && course.error.kind === "not_found") return <CourseNotFound />;
  if (course.isPending) return <div aria-busy="true" role="status" aria-label={PROVISIONAL.summary} className="min-h-[50vh]" />;
  if (course.isError) {
    return (
      <div role="alert" className="flex flex-col items-start gap-4 px-4 py-10 lg:px-12">
        <Notice tone="warning" title={PROVISIONAL.loadError} body={PROVISIONAL.loadErrorBody} />
        <Button variant="secondary" onClick={() => void course.refetch()}>
          {PROVISIONAL.tryAgain}
        </Button>
      </div>
    );
  }
  const preselected = params.get("document");
  const list = combined.data?.items ?? [];

  return (
    <div className="mx-auto flex w-full max-w-[1080px] flex-col gap-8 px-4 py-6 md:px-8 lg:px-12 lg:pt-8 lg:pb-12">
      <Breadcrumb items={[{ label: COURSE_FIGMA.courses, href: "/#courses" }, { label: course.data.name, href: `/courses/${encodeURIComponent(courseId)}` }, { label: COMBINED.createTitle }]} />
      <header className="flex flex-col gap-2">
        <h1 className="text-h1 break-words text-fg">{COMBINED.createTitle}</h1>
        <p className="max-w-[720px] text-body text-fg-secondary">{COMBINED.createBody}</p>
      </header>
      <section aria-label={COMBINED.filesLegend} className="flex min-w-0 flex-col gap-4 rounded-xl border border-line bg-surface p-4 sm:p-6">
        {documents.isPending ? <div aria-busy="true" role="status" aria-label={PROVISIONAL.summary} className="h-24" /> : null}
        {documents.isError ? (
          <div role="alert" className="flex flex-col items-start gap-3">
            <Notice tone="warning" title={PROVISIONAL.loadError} body={PROVISIONAL.loadErrorBody} />
            <Button variant="secondary" onClick={() => void documents.refetch()}>
              {PROVISIONAL.tryAgain}
            </Button>
          </div>
        ) : null}
        {documents.isSuccess ? (
          <SummaryForm
            key={preselected ?? "none"}
            courseId={courseId}
            documents={documents.documents}
            preselected={preselected && documents.documents.some((d) => d.id === preselected && d.status === "ready") ? preselected : null}
          />
        ) : null}
      </section>
      <section aria-labelledby="combined-heading" className="flex flex-col gap-3">
        <h2 id="combined-heading" className="text-h3 text-fg">
          {COMBINED.yourSummaries}
        </h2>
        {combined.isSuccess && list.length === 0 ? <p className="text-body-sm text-fg-secondary">{COMBINED.noCombined}</p> : null}
        <ul className="motion-stagger flex flex-col gap-2">
          {list.map((s) => (
            <li key={s.id}>
              <Link href={combinedSummaryHref(s.id)} className="flex min-w-0 flex-col gap-1 rounded-xl border border-line bg-surface p-4 hover:border-line-strong hover:shadow-md">
                <span className="flex min-w-0 flex-wrap items-center gap-2">
                  <span className="min-w-0 text-title wrap-anywhere text-fg">{s.title}</span>
                  <Tag tone={s.status === "ready" ? "success" : s.status === "failed" ? "danger" : "accent"}>
                    {s.status === "ready" ? "Ready" : s.status === "failed" ? "Failed" : "Generating"}
                  </Tag>
                </span>
                <span className="text-caption text-fg-secondary">{[COMBINED.fromFiles(s.source_documents.length), relativeTime(s.created_at, now)].filter(Boolean).join(" · ")}</span>
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function SummaryForm({ courseId, documents, preselected }: { courseId: string; documents: DocumentOut[]; preselected: string | null }) {
  const router = useRouter();
  const client = useQueryClient();
  const retryAfter = useRetryAfter();
  const [selected, setSelected] = useState<string[]>(preselected ? [preselected] : []);
  const [problem, setProblem] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const { kept, dropped } = prune(selected, documents);
  useEffect(() => {
    if (dropped.length) {
      setSelected((current) => prune(current, documents).kept);
      setNotice(SELECTION_COPY.dropped(dropped.length));
    }
  }, [dropped.length, documents]);

  const create = useCreateSummary(courseId);

  const count = kept.length;
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (create.isPending || retryAfter.blocked || count === 0) return;
    if (count > MAX_SELECTED_DOCUMENTS) {
      setProblem(`Choose at most ${MAX_SELECTED_DOCUMENTS} files for one summary.`);
      return;
    }
    setProblem(null);
    create.mutate(kept, {
      onSuccess: (href) => router.push(href),
      onError: (error) => {
        retryAfter.note(error); // the selection stays as it was, so the reader can retry
        setProblem(summaryRequestError(error));
        if (error instanceof ApiError && (error.code === "document_not_ready" || error.kind === "not_found")) {
          void client.invalidateQueries({ queryKey: queryKeys.documentsOf(courseId) }); // the picker drops stale files
        }
      },
    });
  };

  return (
    <form noValidate onSubmit={submit} className="flex min-w-0 flex-col gap-4">
      <div role="alert" className="empty:sr-only">
        {problem ? <Notice tone="warning" title={problem} /> : null}
      </div>
      {notice ? <Notice tone="info" title={notice} /> : null}
      <DocumentPicker
        legend={COMBINED.filesLegend}
        documents={documents}
        selected={kept}
        disabled={create.isPending}
        hint={count === 0 ? SELECTION_COPY.summaryHint : count === 1 ? COMBINED.singleNote : undefined}
        onChange={(ids) => {
          setNotice(null);
          setSelected(ids);
        }}
      />
      <div className="sticky bottom-0 -mx-4 flex flex-wrap items-center gap-3 border-t border-line bg-surface px-4 py-4 sm:static sm:mx-0 sm:border-0 sm:p-0">
        <Button type="submit" loading={create.isPending} disabled={retryAfter.blocked || count === 0}>
          {create.isPending ? SELECTION_COPY.creatingSummary : SELECTION_COPY.createSummary(count)}
        </Button>
        {count === 0 ? <p className="text-body-sm text-fg-secondary">{SELECTION_COPY.summaryHint}</p> : null}
      </div>
    </form>
  );
}
