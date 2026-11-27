"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useRef, useState } from "react";
import { Button } from "@/design-system/components/Button";
import { Modal } from "@/design-system/components/Modal";
import { Notice } from "@/design-system/components/Notice";
import { Tag } from "@/design-system/components/Tag";
import { useToast } from "@/design-system/components/Toast";
import { Breadcrumb } from "@/design-system/compositions/Breadcrumb";
import { CitationText } from "@/design-system/compositions/CitationText";
import { SummarySection } from "@/design-system/compositions/SummarySection";
import { Icon } from "@/design-system/icons/Icon";
import { useCourse } from "@/features/courses/hooks";
import { FIGMA as COURSE_FIGMA } from "@/features/courses/strings";
import { ResourceNotFound } from "@/features/shell/components/ResourceNotFound";
import { SourceView, type SourceItem } from "@/features/sources/SourceView";
import { FIGMA as SOURCE_FIGMA, PROVISIONAL as SOURCE_COPY } from "@/features/sources/strings";
import { ApiError } from "@/lib/api/errors";
import type { CourseSummaryOut } from "@/lib/api/types";
import { splitStatements } from "@/lib/citations/parse";
import { relativeTime } from "@/lib/format/format";
import { useNow } from "@/lib/format/use-now";
import { useCourseSummary, useDeleteCourseSummary } from "../hooks";
import { generationFailure, summaryLoadProblem } from "../messages";
import { COMBINED, FIGMA, PROVISIONAL } from "../strings";
import { parseSourceParam } from "./SummaryPage";

const CANONICAL_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/** Sections in the order written, grouped under the file they summarise (consecutive sections of one file share a group). */
export function groupByFile(summary: Pick<CourseSummaryOut, "sections" | "source_documents">) {
  const names = new Map(summary.source_documents.map((d) => [d.document_id, d.file_name]));
  const groups: { documentId: string; fileName: string; sections: CourseSummaryOut["sections"] }[] = [];
  for (const section of summary.sections) {
    const id = section.document_id ?? "";
    const last = groups[groups.length - 1];
    if (last && last.documentId === id) last.sections.push(section);
    else groups.push({ documentId: id, fileName: section.file_name || names.get(id) || "", sections: [section] });
  }
  return groups;
}

/**
 * One combined summary: the source files, then the sections grouped by file; every citation names its file and page
 * and opens the exact passage. The backend's lifecycle only: polled while generating, explicit failure otherwise.
 */
export function CourseSummaryPage({ summaryId }: { summaryId: string }) {
  if (!CANONICAL_ID.test(summaryId)) return <ResourceNotFound />;
  return <Loaded summaryId={summaryId} />;
}

function Loaded({ summaryId }: { summaryId: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const now = useNow();
  const toast = useToast();
  const summary = useCourseSummary(summaryId, { enabled: true });
  const data = summary.data;
  const course = useCourse(data?.course_id ?? "", { enabled: Boolean(data) });
  const remove = useDeleteCourseSummary(data?.course_id ?? "");
  const [deleting, setDeleting] = useState(false);
  const cancel = useRef<HTMLButtonElement>(null);
  const trigger = useRef<HTMLElement | null>(null);
  const sources: SourceItem[] = useMemo(() => data?.citations ?? [], [data]);
  const labels = useMemo(() => new Map(sources.map((s) => [s.number, SOURCE_COPY.sourceLabel(s.number, s.file_name, s.citation_label)])), [sources]);
  const selected = parseSourceParam(params.get("source"), data);

  if (summary.isError && summary.error instanceof ApiError && summary.error.kind === "not_found") return <ResourceNotFound />;
  if (summary.isPending) return <div aria-busy="true" role="status" aria-label={PROVISIONAL.summary} className="min-h-[50vh]" />;
  if (!data) {
    const problem = summaryLoadProblem(summary.error);
    return (
      <div role="alert" className="flex flex-col items-start gap-4 px-4 py-10 lg:px-12">
        <Notice tone="warning" title={problem.title} body={problem.body} />
        <Button variant="secondary" onClick={() => void summary.refetch()}>
          {PROVISIONAL.tryAgain}
        </Button>
      </div>
    );
  }

  const courseHref = `/courses/${encodeURIComponent(data.course_id)}`;
  const select = (n: number, from: HTMLElement) => {
    trigger.current = from;
    const next = new URLSearchParams(params.toString());
    next.set("source", String(n));
    router.push(`${pathname}?${next.toString()}`, { scroll: false });
  };
  const closeSource = () => router.replace(pathname, { scroll: false });
  const groups = groupByFile(data);
  const meta = [COMBINED.fromFiles(data.source_documents.length), data.generated_at ? PROVISIONAL.generatedAt(relativeTime(data.generated_at, now)) : null].filter(Boolean).join(" · ");

  return (
    <div className="flex min-h-screen">
      <div className="flex min-w-0 flex-1 flex-col gap-6 px-4 py-6 md:px-8 lg:px-12 lg:pt-8 lg:pb-12">
        <Breadcrumb
          items={[
            { label: COURSE_FIGMA.courses, href: "/#courses" },
            { label: course.data?.name ?? "…", href: courseHref },
            { label: COMBINED.createTitle, href: `${courseHref}/summaries` },
            { label: data.title },
          ]}
        />
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex min-w-0 flex-col gap-2">
            <h1 className="text-h1 wrap-anywhere text-fg">{data.title}</h1>
            <div className="flex flex-wrap items-center gap-2">
              {data.source_documents.length > 1 ? <Tag tone="accent">{COMBINED.combinedBadge}</Tag> : null}
              <span className="text-body-sm text-fg-secondary">{meta}</span>
            </div>
          </div>
          <Button variant="secondary" onClick={() => setDeleting(true)} leadingIcon={<Icon name="trash" size={16} />}>
            {COMBINED.delete}
          </Button>
        </div>

        <section aria-labelledby="source-files" className="flex flex-col gap-2">
          <h2 id="source-files" className="text-caption-strong text-fg-secondary">
            {COMBINED.sourceFiles}
          </h2>
          <ul className="flex flex-wrap gap-2">
            {data.source_documents.map((d) => (
              <li key={d.document_id} className="min-w-0 max-w-full">
                <Link
                  href={`${courseHref}?file=${encodeURIComponent(d.document_id)}`}
                  aria-label={COMBINED.openFile(d.file_name)}
                  className="flex min-h-11 max-w-full items-center gap-2 rounded-full border border-line bg-surface px-3 text-label text-fg hover:bg-subtle"
                >
                  <Icon name="file" size={16} className="text-fg-secondary" />
                  <span className="min-w-0 truncate" title={d.file_name}>
                    {d.file_name}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>

        {summary.pollingStopped ? (
          <div role="alert" className="flex flex-col items-start gap-4">
            <Notice tone="warning" title={PROVISIONAL.pollingStopped} body={PROVISIONAL.pollingStoppedBody} />
            <Button variant="secondary" onClick={summary.resumePolling}>
              {PROVISIONAL.tryAgain}
            </Button>
          </div>
        ) : null}
        <div role="status" className="empty:sr-only">
          {data.status === "generating" ? <Notice tone="info" title={COMBINED.generatingTitle} body={COMBINED.generatingBody} /> : null}
        </div>
        {data.status === "failed" ? <Notice tone="warning" title={PROVISIONAL.failedTitle} body={generationFailure(data.error_code)} /> : null}
        {data.status === "ready" ? (
          <>
            <p className="text-body text-fg-secondary">{COMBINED.intro}</p>
            <div className="flex flex-col gap-8">
              {groups.map((group, g) => (
                <section key={`${group.documentId}-${g}`} aria-label={group.fileName} className="motion-enter-fast flex flex-col gap-3">
                  <h2 className="flex min-w-0 items-center gap-2 text-h3 text-fg">
                    <Icon name="file" size={20} className="text-fg-secondary" />
                    <span className="min-w-0 wrap-anywhere">{group.fileName}</span>
                  </h2>
                  {group.sections.map((section, index) => {
                    const range = section.source_range ? PROVISIONAL.range(section.source_range.kind, section.source_range.start, section.source_range.end) : null;
                    return (
                      <SummarySection
                        key={`${index}-${section.heading}`}
                        headingLevel={3}
                        heading={section.heading}
                        caption={[FIGMA.sources(section.citations.length), range].filter(Boolean).join(" · ")}
                        defaultExpanded={g === 0 && index < 2}
                        statements={splitStatements(section.text).map((statement, i) => (
                          <CitationText key={i} text={statement} labels={labels} activeNumber={selected} onSelect={select} />
                        ))}
                      />
                    );
                  })}
                </section>
              ))}
            </div>
          </>
        ) : null}
      </div>
      {data.status === "ready" ? (
        <SourceView
          key={summaryId}
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
      <Modal
        open={deleting}
        busy={remove.isPending}
        initialFocus={cancel}
        title={COMBINED.deleteTitle}
        description={COMBINED.deleteBody}
        onClose={() => !remove.isPending && setDeleting(false)}
        footer={
          <>
            <Button ref={cancel} variant="secondary" disabled={remove.isPending} onClick={() => setDeleting(false)}>
              {COMBINED.cancel}
            </Button>
            <Button
              variant="danger"
              loading={remove.isPending}
              onClick={() =>
                !remove.isPending &&
                remove.mutate(summaryId, {
                  onSuccess: () => {
                    toast(COMBINED.deleted, "success");
                    router.replace(`${courseHref}/summaries`);
                  },
                })
              }
            >
              {COMBINED.delete}
            </Button>
          </>
        }
      />
    </div>
  );
}
