"use client";

import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Button, ButtonLink } from "@/design-system/components/Button";
import { EmptyState } from "@/design-system/components/EmptyState";
import { Notice } from "@/design-system/components/Notice";
import { Tag, type TagTone } from "@/design-system/components/Tag";
import { useToast } from "@/design-system/components/Toast";
import { Breadcrumb } from "@/design-system/compositions/Breadcrumb";
import { StatCard } from "@/design-system/compositions/StatCard";
import { Icon } from "@/design-system/icons/Icon";
import { CourseFormModal } from "@/features/courses/components/CourseFormModal";
import { CourseNotFound } from "@/features/courses/components/CourseNotFound";
import { DeleteCourseModal } from "@/features/courses/components/DeleteCourseModal";
import { forgetCourse, useCourse } from "@/features/courses/hooks";
import { FIGMA as COURSE_FIGMA, PROVISIONAL as COURSE_COPY } from "@/features/courses/strings";
import { DeleteDocumentModal } from "@/features/documents/components/DeleteDocumentModal";
import { FileDetails } from "@/features/documents/components/FileDetails";
import { useDocument, useDocuments, useDownloadDocument, useRetryDocument } from "@/features/documents/hooks";
import { documentActionError } from "@/features/documents/messages";
import { documentView, summarise } from "@/features/documents/status";
import { FIGMA, PROVISIONAL } from "@/features/documents/strings";
import { ApiError } from "@/lib/api/errors";
import type { DocumentOut } from "@/lib/api/types";
import { useNow } from "@/lib/format/use-now";

const TAG_TONE: Record<string, TagTone> = { extracting: "accent", indexed: "success", failed: "danger", unsupported: "danger", empty: "danger" };

/**
 * Course Workspace (UI §8.3; gates GF0B-10..13, -19..22). Three columns as drawn (Materials 300 · centre · details 340)
 * from 1280 px; below that the details move under the centre column, and below 1024 px everything stacks (provisional).
 * Mastery, topics, tabs, the OCR notice and "Ask your materials" have no backend data or belong to F1 and are omitted.
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
  const [renaming, setRenaming] = useState(false);
  const [deletingCourse, setDeletingCourse] = useState(false);
  const [deletingDoc, setDeletingDoc] = useState<DocumentOut | null>(null);

  // After deletion this page stops observing the course, then drops its cache while navigating away (GF0B-13).
  useEffect(() => {
    if (deleted) forgetCourse(client, courseId);
  }, [deleted, client, courseId]);

  const requested = params.get("file");
  const inList = requested ? documents.documents.find((doc) => doc.id === requested) : undefined;
  const single = useDocument(requested, Boolean(requested) && documents.isSuccess && !inList);
  const fetched = single.data?.course_id === courseId ? single.data : undefined; // a file of another course is not shown here
  const selected: DocumentOut | undefined = inList ?? fetched ?? (requested ? undefined : documents.documents[0]);

  if (course.isError && course.error instanceof ApiError && course.error.kind === "not_found") return <CourseNotFound />;
  if (course.isPending) return <div aria-busy="true" role="status" aria-label={COURSE_COPY.loadingCourses} className="min-h-[50vh]" />;
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
  const summary = summarise(documents.documents, documents.complete);
  const uploadHref = `/courses/${encodeURIComponent(courseId)}/upload`;
  const fileHref = (id: string) => `/courses/${encodeURIComponent(courseId)}?file=${encodeURIComponent(id)}`;
  const runRetry = (doc: DocumentOut) => {
    if (retry.isPending) return;
    retry.mutate(doc.id, { onError: (e) => toast(documentActionError(e), "warning") });
  };

  const note = [summary.processing ? COURSE_COPY.processing(summary.processing) : null, summary.attention ? `${summary.attention} failed` : null]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="grid min-h-screen grid-cols-1 lg:grid-cols-[300px_minmax(0,1fr)] xl:grid-cols-[300px_minmax(0,1fr)_340px]">
      {/* Centre column (first in reading order) */}
      <div className="flex min-w-0 flex-col gap-6 px-4 py-6 md:px-8 lg:col-start-2 lg:row-start-1 lg:px-10 lg:pt-8 lg:pb-10">
        <Breadcrumb items={[{ label: COURSE_FIGMA.courses, href: "/#courses" }, { label: data.name }]} />
        <div className="flex flex-wrap items-start justify-between gap-4">
          <h1 className="min-w-0 text-h1 break-words text-fg">{data.name}</h1>
          <div className="flex flex-wrap gap-3">
            <ButtonLink href={`/courses/${encodeURIComponent(courseId)}/chat`}>{FIGMA.askMaterials}</ButtonLink>
            <Button variant="secondary" onClick={() => setRenaming(true)}>
              {COURSE_COPY.rename}
            </Button>
            <Button variant="secondary" onClick={() => setDeletingCourse(true)}>
              {COURSE_FIGMA.deleteCourse}
            </Button>
          </div>
        </div>
        {data.description ? <p className="text-body break-words text-fg-secondary">{data.description}</p> : null}

        {documents.isError && documents.documents.length === 0 ? (
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

        {documents.isSuccess && summary.total > 0 ? (
          <div className="flex flex-wrap gap-6">
            <StatCard label={FIGMA.filesIndexed} value={`${summary.indexed} of ${summary.total}${summary.complete ? "" : "+"}`} note={note || undefined} />
          </div>
        ) : null}
        {documents.isSuccess && summary.total === 0 ? (
          <div className="rounded-xl border border-line bg-surface">
            <EmptyState
              size="panel"
              icon="upload"
              title={FIGMA.noMaterialsTitle}
              body={FIGMA.noMaterialsBody}
              action={<ButtonLink href={uploadHref}>{FIGMA.uploadFiles}</ButtonLink>}
            />
          </div>
        ) : null}
      </div>

      {/* Materials column */}
      <section
        aria-labelledby="materials-heading"
        className="flex min-w-0 flex-col gap-4 border-line px-4 py-6 md:px-8 lg:col-start-1 lg:row-span-2 lg:row-start-1 lg:border-r lg:px-4"
      >
        <div className="flex items-baseline justify-between gap-2">
          <h2 id="materials-heading" className="text-title text-fg">
            {FIGMA.materials}
          </h2>
          {documents.isSuccess ? <span className="text-caption text-fg-secondary">{PROVISIONAL.fileCount(summary.total)}{summary.complete ? "" : "+"}</span> : null}
        </div>
        <ButtonLink href={uploadHref} variant="secondary" fullWidth>
          {FIGMA.addFiles}
        </ButtonLink>
        {documents.isPending ? <div aria-busy="true" role="status" aria-label={FIGMA.materials} className="h-20" /> : null}
        <ul className="flex flex-col gap-1">
          {documents.documents.map((doc) => {
            const view = documentView(doc, now);
            const isSelected = selected?.id === doc.id;
            return (
              <li key={doc.id} className={`flex flex-col rounded-md border ${isSelected ? "border-accent-subtle-border bg-accent-subtle" : "border-transparent"}`}>
                <Link href={fileHref(doc.id)} scroll={false} aria-current={isSelected ? "true" : undefined} className="flex flex-col gap-1 rounded-md px-3 py-2 hover:bg-subtle">
                  <span className="flex items-start gap-2">
                    <Icon name="file" size={20} />
                    <span className="min-w-0 text-label break-all text-fg">{doc.file_name}</span>
                  </span>
                  <span className="flex flex-wrap items-center gap-2 pl-7">
                    <Tag tone={TAG_TONE[view.status] ?? "neutral"}>{view.tag}</Tag>
                  </span>
                </Link>
                {view.canRetry ? (
                  <button
                    type="button"
                    onClick={() => runRetry(doc)}
                    disabled={retry.isPending}
                    aria-label={PROVISIONAL.retryLabel(doc.file_name)}
                    className="ml-10 min-h-11 self-start rounded-md px-1 text-label text-fg-link hover:underline disabled:text-disabled-fg"
                  >
                    {FIGMA.retry}
                  </button>
                ) : null}
              </li>
            );
          })}
        </ul>
        {documents.hasNextPage ? (
          <Button variant="secondary" loading={documents.isFetchingNextPage} onClick={() => void documents.fetchNextPage()}>
            {PROVISIONAL.showMoreFiles}
          </Button>
        ) : null}
      </section>

      {/* Details column */}
      <aside
        aria-label={FIGMA.selectedFile}
        className="min-w-0 border-line px-4 py-6 md:px-8 lg:col-start-2 lg:row-start-2 lg:px-10 xl:col-start-3 xl:row-span-2 xl:row-start-1 xl:border-l xl:px-6 xl:py-8"
      >
        {selected ? (
          <FileDetails
            document={selected}
            now={now}
            downloading={download.isPending && download.variables?.id === selected.id}
            onDownload={() => {
              if (download.isPending) return;
              download.mutate(selected, { onError: (e) => toast(e instanceof ApiError ? documentActionError(e) : PROVISIONAL.downloadFailed, "warning") });
            }}
            retrying={retry.isPending}
            onRetry={() => runRetry(selected)}
            onDelete={() => setDeletingDoc(selected)}
            summaryHref={`/courses/${encodeURIComponent(courseId)}/documents/${encodeURIComponent(selected.id)}/summary`}
          />
        ) : documents.isSuccess && summary.total > 0 ? (
          <p className="text-body-sm text-fg-secondary">{requested ? PROVISIONAL.notFound : PROVISIONAL.selectHint}</p>
        ) : null}
      </aside>

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
          if (requested === id) router.replace(`/courses/${encodeURIComponent(courseId)}`, { scroll: false });
        }}
      />
    </div>
  );
}
