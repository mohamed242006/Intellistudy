"use client";

import { useState } from "react";
import { Button, ButtonLink } from "@/design-system/components/Button";
import { FileUploadRow } from "@/design-system/components/FileUploadRow";
import { Notice } from "@/design-system/components/Notice";
import { useToast } from "@/design-system/components/Toast";
import { Breadcrumb } from "@/design-system/compositions/Breadcrumb";
import { Icon } from "@/design-system/icons/Icon";
import { CourseNotFound } from "@/features/courses/components/CourseNotFound";
import { useCourse } from "@/features/courses/hooks";
import { FIGMA as COURSE_FIGMA, PROVISIONAL as COURSE_COPY } from "@/features/courses/strings";
import { DeleteDocumentModal } from "@/features/documents/components/DeleteDocumentModal";
import { useDocuments, useRetryDocument } from "@/features/documents/hooks";
import { documentActionError } from "@/features/documents/messages";
import { documentView, isInProgress, sizeLabel } from "@/features/documents/status";
import { FIGMA, PROVISIONAL } from "@/features/documents/strings";
import { ApiError } from "@/lib/api/errors";
import type { DocumentOut } from "@/lib/api/types";
import { plural } from "@/lib/format/format";
import { useNow } from "@/lib/format/use-now";
import { useUploadQueue, type UploadItem } from "../useUploadQueue";
import { Dropzone } from "./Dropzone";

/**
 * Upload flow (UI §8.4; gates GF0B-14..21). One list: this page's in-flight rows (client ids) on top, then the course's
 * documents from the server, newest first; a row moves from the first group to the second when the backend accepts it.
 */
export function UploadPage({ courseId }: { courseId: string }) {
  const course = useCourse(courseId);
  const documents = useDocuments(courseId, { poll: true });
  const activeCount = documents.documents.filter((doc) => isInProgress(doc.status)).length;
  const queue = useUploadQueue(courseId, activeCount);
  const retry = useRetryDocument(courseId);
  const toast = useToast();
  const now = useNow();
  const [removing, setRemoving] = useState<DocumentOut | null>(null);

  if (course.isError && course.error instanceof ApiError && course.error.kind === "not_found") return <CourseNotFound />;

  const courseName = course.data?.name ?? "";
  const views = documents.documents.map((doc) => ({ doc, view: documentView(doc, now) }));
  const indexed = views.filter((v) => v.view.status === "indexed").length;
  const inProgress = views.filter((v) => v.view.status === "extracting").length + queue.items.filter((i) => i.phase !== "problem").length;
  const attention = views.length + queue.items.length - indexed - inProgress;
  const total = queue.items.length + views.length;

  return (
    <div className="flex flex-col gap-8 px-4 py-6 md:px-8 lg:px-12 lg:pt-10 lg:pb-12">
      <Breadcrumb
        items={[
          { label: COURSE_FIGMA.courses, href: "/#courses" },
          ...(courseName ? [{ label: courseName, href: `/courses/${encodeURIComponent(courseId)}` }] : []),
          { label: FIGMA.addMaterials },
        ]}
      />
      <header className="flex flex-col gap-2">
        <h1 className="text-h1 text-fg">{FIGMA.addMaterials}</h1>
        <p className="text-body text-fg-secondary">{FIGMA.addMaterialsSubtitle}</p>
      </header>

      <Dropzone onFiles={queue.add} />

      <section aria-labelledby="upload-list-heading" className="flex flex-col gap-4">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <h2 id="upload-list-heading" className="text-h3 text-fg">
            {plural(total, "file")}
          </h2>
          {total > 0 ? (
            <p className="text-body-sm text-fg-secondary">
              {[FIGMA.indexedCount(indexed), FIGMA.inProgress(inProgress), FIGMA.needAttention(attention)].join(" · ")}
            </p>
          ) : null}
        </div>
        {documents.pollingStopped ? (
          <div role="alert" className="flex flex-col items-start gap-4">
            <Notice tone="warning" title={PROVISIONAL.pollingStopped} body={PROVISIONAL.pollingStoppedBody} />
            <Button variant="secondary" onClick={documents.resumePolling}>
              {PROVISIONAL.tryAgain}
            </Button>
          </div>
        ) : null}
        {documents.isError && documents.documents.length === 0 ? (
          <div role="alert" className="flex flex-col items-start gap-4">
            <Notice tone="warning" title={PROVISIONAL.documentsError} />
            <Button variant="secondary" onClick={() => void documents.refetch()}>
              {PROVISIONAL.tryAgain}
            </Button>
          </div>
        ) : null}
        <ul className="flex flex-col gap-3" aria-busy={documents.isPending || undefined}>
          {queue.items.map((item) => (
            <li key={item.id}>
              <QueueRow item={item} blockedByCapacity={queue.blockedByCapacity} onRetry={() => queue.retry(item.id)} onRemove={() => queue.remove(item.id)} />
            </li>
          ))}
          {views.map(({ doc, view }) => (
            <li key={doc.id}>
              <FileUploadRow
                name={doc.file_name}
                status={view.status}
                tag={view.tag}
                detail={view.detail}
                actions={
                  view.status === "indexed" ? (
                    <ButtonLink variant="ghost" href={`/courses/${encodeURIComponent(courseId)}?file=${encodeURIComponent(doc.id)}`} aria-label={PROVISIONAL.openLabel(doc.file_name)}>
                      {FIGMA.open}
                    </ButtonLink>
                  ) : view.canRetry ? (
                    <Button
                      variant="secondary"
                      aria-label={PROVISIONAL.retryLabel(doc.file_name)}
                      loading={retry.isPending && retry.variables === doc.id}
                      onClick={() => !retry.isPending && retry.mutate(doc.id, { onError: (e) => toast(documentActionError(e), "warning") })}
                    >
                      {FIGMA.retry}
                    </Button>
                  ) : view.status === "unsupported" || view.status === "empty" ? (
                    <Button variant="ghost" aria-label={PROVISIONAL.removeLabel(doc.file_name)} onClick={() => setRemoving(doc)}>
                      {FIGMA.remove}
                    </Button>
                  ) : null
                }
              />
            </li>
          ))}
        </ul>
        <p className="sr-only" aria-live="polite" data-testid="upload-announcer">
          {queue.announcement}
        </p>
      </section>

      <p className="flex items-center gap-2 text-body-sm text-fg-secondary">
        <Icon name="lock" size={16} />
        <span>{FIGMA.privacy}</span>
      </p>

      <DeleteDocumentModal courseId={courseId} document={removing} onClose={() => setRemoving(null)} />
      {course.isError && !(course.error instanceof ApiError && course.error.kind === "not_found") ? (
        <Notice tone="warning" title={COURSE_COPY.loadError} body={COURSE_COPY.loadErrorBody} />
      ) : null}
    </div>
  );
}

function QueueRow({ item, blockedByCapacity, onRetry, onRemove }: { item: UploadItem; blockedByCapacity: boolean; onRetry: () => void; onRemove: () => void }) {
  const name = item.file.name;
  if (item.phase === "uploading") {
    return (
      <FileUploadRow
        name={name}
        status="uploading"
        tag={FIGMA.uploadingTag(item.progress)}
        detail={FIGMA.uploadingDetail(item.progress, sizeLabel(item.file.size))}
        progress={item.progress}
        actions={
          <Button variant="ghost" aria-label={PROVISIONAL.cancelLabel(name)} onClick={onRemove}>
            {FIGMA.cancel}
          </Button>
        }
      />
    );
  }
  if (item.phase === "pending") {
    return (
      <FileUploadRow
        name={name}
        status="waiting"
        tag={PROVISIONAL.waiting}
        detail={blockedByCapacity ? PROVISIONAL.waitingCapacity : PROVISIONAL.waitingDetail}
        actions={
          <Button variant="ghost" aria-label={PROVISIONAL.removeLabel(name)} onClick={onRemove}>
            {FIGMA.remove}
          </Button>
        }
      />
    );
  }
  const problem = item.problem!;
  const tag = problem.status === "unsupported" ? FIGMA.notSupported : problem.status === "empty" ? FIGMA.empty : FIGMA.failed;
  return (
    <FileUploadRow
      name={name}
      status={problem.status}
      tag={tag}
      detail={problem.message}
      actions={
        <>
          {problem.retryable ? (
            <Button variant="secondary" aria-label={PROVISIONAL.retryLabel(name)} onClick={onRetry}>
              {FIGMA.retry}
            </Button>
          ) : null}
          <Button variant="ghost" aria-label={PROVISIONAL.removeLabel(name)} onClick={onRemove}>
            {FIGMA.remove}
          </Button>
        </>
      }
    />
  );
}
