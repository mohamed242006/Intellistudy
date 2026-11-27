"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useRef } from "react";
import { Button } from "@/design-system/components/Button";
import { EmptyState } from "@/design-system/components/EmptyState";
import { Notice } from "@/design-system/components/Notice";
import { Tag } from "@/design-system/components/Tag";
import { Breadcrumb } from "@/design-system/compositions/Breadcrumb";
import { CitationText } from "@/design-system/compositions/CitationText";
import { SummarySection } from "@/design-system/compositions/SummarySection";
import { useCourse } from "@/features/courses/hooks";
import { FIGMA as COURSE_FIGMA } from "@/features/courses/strings";
import { useDocument } from "@/features/documents/hooks";
import { ResourceNotFound } from "@/features/shell/components/ResourceNotFound";
import { SourceView, type SourceItem } from "@/features/sources/SourceView";
import { FIGMA as SOURCE_FIGMA, PROVISIONAL as SOURCE_COPY } from "@/features/sources/strings";
import { ApiError } from "@/lib/api/errors";
import type { SummaryOut } from "@/lib/api/types";
import { splitStatements } from "@/lib/citations/parse";
import { relativeTime } from "@/lib/format/format";
import { useRetryAfter } from "@/lib/hooks/use-retry-after";
import { useNow } from "@/lib/format/use-now";
import { useRequestSummary, useSummary } from "../hooks";
import { generationFailure, summaryLoadProblem, summaryRequestError } from "../messages";
import { FIGMA, PROVISIONAL } from "../strings";

/** `?source=n`: a positive integer naming one of this summary's citation numbers; anything else is ignored. */
export function parseSourceParam(raw: string | null, summary: Pick<SummaryOut, "citations"> | null | undefined): number | null {
  if (!raw || !/^[1-9]\d{0,3}$/.test(raw)) return null;
  const n = Number(raw);
  return summary?.citations.some((c) => c.number === n) ? n : null;
}

/**
 * Summary page (UI §8.5; gates GF1-01..10, GF1-17, GF1-20..22). Real data only: the document (same course), its
 * summary and the summary's own citations. The lifecycle is the backend's: POST once, then poll while `pending`.
 */
export function SummaryPage({ courseId, documentId }: { courseId: string; documentId: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const now = useNow();
  const course = useCourse(courseId);
  const document = useDocument(documentId, true, { live: true });
  const doc = document.data && document.data.course_id === courseId ? document.data : undefined;
  const summary = useSummary(documentId, { enabled: doc?.status === "ready" });
  const request = useRequestSummary(documentId);
  const retryAfter = useRetryAfter();
  const trigger = useRef<HTMLElement | null>(null);

  const data = summary.data;
  const selected = parseSourceParam(params.get("source"), data);
  const sources: SourceItem[] = useMemo(() => data?.citations ?? [], [data]);
  const labels = useMemo(
    () => new Map(sources.map((s) => [s.number, SOURCE_COPY.sourceLabel(s.number, s.file_name, s.citation_label)])),
    [sources],
  );

  if (document.isError && document.error instanceof ApiError && document.error.kind === "not_found") return <ResourceNotFound />;
  if (document.data && !doc) return <ResourceNotFound />; // a file of another course is not shown under this course
  if (document.isPending || course.isPending) return <div aria-busy="true" role="status" aria-label={PROVISIONAL.summary} className="min-h-[50vh]" />;
  if (!doc || course.isError) {
    const problem = summaryLoadProblem(document.error ?? course.error);
    return (
      <div role="alert" className="flex flex-col items-start gap-4 px-4 py-10 lg:px-12">
        <Notice tone="warning" title={problem.title} body={problem.body} />
        <Button variant="secondary" onClick={() => void Promise.all([document.refetch(), course.refetch()])}>
          {PROVISIONAL.tryAgain}
        </Button>
      </div>
    );
  }

  const select = (n: number, from: HTMLElement) => {
    trigger.current = from;
    const next = new URLSearchParams(params.toString());
    next.set("source", String(n));
    router.push(`${pathname}?${next.toString()}`, { scroll: false });
  };
  const closeSource = () => {
    const next = new URLSearchParams(params.toString());
    next.delete("source");
    const query = next.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };
  const generate = (regenerate: boolean) => {
    if (request.isPending || retryAfter.blocked) return;
    request.mutate(regenerate, { onError: retryAfter.note });
  };

  const unit = doc.file_type === "pptx" ? "slide" : "page";
  const meta = [doc.file_name, doc.page_count !== null ? `${doc.page_count} ${doc.page_count === 1 ? unit : `${unit}s`}` : null, data?.generated_at ? PROVISIONAL.generatedAt(relativeTime(data.generated_at, now)) : null]
    .filter(Boolean)
    .join(" · ");
  const requestError = request.isError ? summaryRequestError(request.error) : null;

  return (
    <div className="flex min-h-screen">
      <div className="flex min-w-0 flex-1 flex-col gap-6 px-4 py-6 md:px-8 lg:px-12 lg:pt-8 lg:pb-12">
        <Breadcrumb
          items={[
            { label: COURSE_FIGMA.courses, href: "/#courses" },
            { label: course.data!.name, href: `/courses/${encodeURIComponent(courseId)}` },
            { label: doc.file_name },
          ]}
        />
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex min-w-0 flex-col gap-2">
            <h1 className="text-h1 break-words text-fg">{FIGMA.summaryTitle(doc.file_name)}</h1>
            <div className="flex flex-wrap items-center gap-2">
              {doc.status === "ready" ? <Tag tone="success">{FIGMA.indexed}</Tag> : null}
              <span className="text-body-sm wrap-anywhere text-fg-secondary">{meta}</span>
            </div>
          </div>
          {data?.status === "ready" ? (
            <Button variant="secondary" loading={request.isPending || data.pending} disabled={retryAfter.blocked} onClick={() => generate(true)}>
              {FIGMA.regenerate}
            </Button>
          ) : null}
        </div>

        <div role="alert" className="empty:sr-only">
          {requestError ? <Notice tone="warning" title={requestError} /> : null}
        </div>

        {doc.status !== "ready" ? (
          <Notice
            tone="info"
            title={doc.status === "failed" ? PROVISIONAL.failedFileTitle : PROVISIONAL.notReadyTitle}
            body={doc.status === "failed" ? PROVISIONAL.failedFileBody : PROVISIONAL.notReadyBody}
          />
        ) : summary.isPending ? (
          <div aria-busy="true" role="status" aria-label={PROVISIONAL.summary} className="h-40" />
        ) : summary.isError && data === undefined ? (
          <div role="alert" className="flex flex-col items-start gap-4">
            <Notice tone="warning" title={summaryLoadProblem(summary.error).title} body={summaryLoadProblem(summary.error).body} />
            <Button variant="secondary" onClick={() => void summary.refetch()}>
              {PROVISIONAL.tryAgain}
            </Button>
          </div>
        ) : data === null ? (
          <div className="rounded-xl border border-line bg-surface">
            <EmptyState
              size="panel"
              icon="layers"
              title={PROVISIONAL.noSummaryTitle}
              body={PROVISIONAL.noSummaryBody}
              action={
                <Button loading={request.isPending} disabled={retryAfter.blocked} onClick={() => generate(false)}>
                  {PROVISIONAL.generate}
                </Button>
              }
            />
          </div>
        ) : data ? (
          <SummaryBody
            summary={data}
            selected={selected}
            labels={labels}
            onSelect={select}
            onRetry={() => generate(data.status === "ready")}
            retryDisabled={retryAfter.blocked || request.isPending}
            pollingStopped={summary.pollingStopped}
            resumePolling={summary.resumePolling}
          />
        ) : null}
      </div>
      {data?.status === "ready" ? (
        <SourceView
          key={documentId}
          sources={sources}
          selected={selected}
          listTitle={SOURCE_FIGMA.allSourcesSummary}
          showContext={false}
          onSelect={select}
          onClose={closeSource}
          returnFocus={() => trigger.current}
          alwaysShowPanel
        />
      ) : null}
    </div>
  );
}

function SummaryBody({ summary, selected, labels, onSelect, onRetry, retryDisabled, pollingStopped, resumePolling }: {
  summary: SummaryOut;
  selected: number | null;
  labels: ReadonlyMap<number, string>;
  onSelect: (n: number, trigger: HTMLElement) => void;
  onRetry: () => void;
  retryDisabled: boolean;
  pollingStopped: boolean;
  resumePolling: () => void;
}) {
  return (
    <div className="flex flex-col gap-6">
      {pollingStopped ? (
        <div role="alert" className="flex flex-col items-start gap-4">
          <Notice tone="warning" title={PROVISIONAL.pollingStopped} body={PROVISIONAL.pollingStoppedBody} />
          <Button variant="secondary" onClick={resumePolling}>
            {PROVISIONAL.tryAgain}
          </Button>
        </div>
      ) : null}
      <div role="status" className="empty:sr-only">
        {summary.status === "generating" ? <Notice tone="info" title={PROVISIONAL.generatingTitle} body={PROVISIONAL.generatingBody} /> : null}
        {summary.status === "ready" && summary.pending ? <Notice tone="info" title={PROVISIONAL.regeneratingTitle} body={PROVISIONAL.regeneratingBody} /> : null}
      </div>
      {summary.status === "failed" ? (
        <div className="flex flex-col items-start gap-4">
          <Notice tone="warning" title={PROVISIONAL.failedTitle} body={generationFailure(summary.error_code)} />
          <Button variant="secondary" disabled={retryDisabled} onClick={onRetry}>
            {PROVISIONAL.tryAgain}
          </Button>
        </div>
      ) : null}
      {summary.status === "ready" && summary.error_code && !summary.pending ? (
        <Notice tone="warning" title={PROVISIONAL.lastRegenerationFailed} body={generationFailure(summary.error_code)} />
      ) : null}
      {summary.status === "ready" ? (
        <>
          <p className="text-body text-fg-secondary">{FIGMA.intro}</p>
          <div className="flex flex-col gap-4">
            {summary.sections.map((section, index) => {
              const range = section.source_range ? PROVISIONAL.range(section.source_range.kind, section.source_range.start, section.source_range.end) : null;
              return (
                <SummarySection
                  key={`${index}-${section.heading}`}
                  heading={section.heading}
                  caption={[FIGMA.sources(section.citations.length), range].filter(Boolean).join(" · ")}
                  defaultExpanded={index < 2}
                  statements={splitStatements(section.text).map((statement, i) => (
                    <CitationText key={i} text={statement} labels={labels} activeNumber={selected} onSelect={onSelect} />
                  ))}
                />
              );
            })}
          </div>
        </>
      ) : null}
    </div>
  );
}
