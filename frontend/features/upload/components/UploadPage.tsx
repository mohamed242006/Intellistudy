"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Button, ButtonLink } from "@/design-system/components/Button";
import { Modal } from "@/design-system/components/Modal";
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
 * Upload flow (UI §8.4; gates GF0B-14..21). One list: this page's rows (client ids) on top, then the course's documents
 * from the server, newest first; a row moves from the first group to the second when the backend accepts it.
 *
 * Choosing files only stages them. "Add this file / Add these files" submits them; when the backend has accepted every
 * submitted file the page shows a short success state, fades out and opens the course workspace (client navigation),
 * where processing continues visibly. If some files failed, nothing is hidden: the counts, Retry and Remove stay, and
 * "Continue with uploaded files" is offered. Leaving with staged or uploading files asks first.
 */
export function UploadPage({ courseId }: { courseId: string }) {
  const router = useRouter();
  const course = useCourse(courseId);
  const documents = useDocuments(courseId, { poll: true });
  const activeCount = documents.documents.filter((doc) => isInProgress(doc.status)).length;
  const queue = useUploadQueue(courseId, activeCount);
  const retry = useRetryDocument(courseId);
  const toast = useToast();
  const now = useNow();
  const [removing, setRemoving] = useState<DocumentOut | null>(null);
  const workspaceHref = `/courses/${encodeURIComponent(courseId)}`;
  const outcomeRef = useRef<HTMLDivElement>(null);
  const batch = queue.batch;
  const succeeded = Boolean(batch?.done && batch.failed === 0 && batch.accepted > 0 && queue.staged === 0);
  const [leaving, setLeaving] = useState(false);
  const left = useRef(false);

  const goToCourse = (accepted: number) => {
    if (left.current) return;
    left.current = true;
    toast(PROVISIONAL.addedToast(accepted), "success");
    router.push(workspaceHref);
  };

  // Every submitted file was accepted: success state, then a short exit transition, then the course workspace.
  useEffect(() => {
    if (!succeeded || leaving) return;
    setLeaving(true);
  }, [succeeded, leaving]);
  useEffect(() => {
    if (!leaving || !batch) return;
    const reduce = typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    // With motion the exit animation's end navigates; this only covers a missed animationend (or reduced motion).
    const timer = setTimeout(() => goToCourse(batch.accepted), reduce ? 0 : 700);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [leaving]);
  // A partial failure or a failure moves focus to the outcome, so keyboard and screen-reader users land on it.
  const outcome = batch?.done && batch.failed > 0 ? `${batch.accepted}:${batch.failed}` : null;
  useEffect(() => {
    if (outcome) outcomeRef.current?.focus();
  }, [outcome]);

  if (course.isError && course.error instanceof ApiError && course.error.kind === "not_found") return <CourseNotFound />;

  const courseName = course.data?.name ?? "";
  const views = documents.documents.map((doc) => ({ doc, view: documentView(doc, now) }));
  const indexed = views.filter((v) => v.view.status === "indexed").length;
  const inProgress = views.filter((v) => v.view.status === "extracting").length + queue.items.filter((i) => i.phase === "pending" || i.phase === "uploading").length;
  const attention = views.length + queue.items.length - indexed - inProgress - queue.staged;
  const total = queue.items.length + views.length;

  return (
    <div
      className={`flex flex-col gap-8 px-4 py-6 md:px-8 lg:px-12 lg:pt-10 lg:pb-12 ${leaving ? "motion-leave" : ""}`}
      onAnimationEnd={(event) => {
        if (leaving && event.target === event.currentTarget && batch) goToCourse(batch.accepted);
      }}
    >
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
        <AddBar
          staged={queue.staged}
          batch={batch}
          succeeded={succeeded}
          outcomeRef={outcomeRef}
          onSubmit={queue.submit}
          onContinue={() => batch && goToCourse(batch.accepted)}
        />
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
                    <ButtonLink variant="ghost" href={`/courses/${encodeURIComponent(courseId)}/documents/${encodeURIComponent(doc.id)}/summary`} aria-label={PROVISIONAL.openLabel(doc.file_name)}>
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
      <LeaveGuard active={queue.unsaved && !leaving} staged={queue.staged} />
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
  if (item.phase === "selected") {
    return (
      <FileUploadRow
        name={name}
        status="waiting"
        tag={PROVISIONAL.selectedTag}
        detail={PROVISIONAL.selectedDetail(sizeLabel(item.file.size))}
        actions={
          <Button variant="ghost" aria-label={PROVISIONAL.removeLabel(name)} onClick={onRemove}>
            {FIGMA.remove}
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

type BatchView = { active: number; failed: number; accepted: number; done: boolean } | null;

/**
 * The explicit completion action and the outcome of the last submission. The button keeps one element (stable focus)
 * while its text follows the state: "Add this file" / "Add these files" → "Adding 3 files…" → "3 files added".
 */
function AddBar({ staged, batch, succeeded, outcomeRef, onSubmit, onContinue }: {
  staged: number;
  batch: BatchView;
  succeeded: boolean;
  outcomeRef: React.RefObject<HTMLDivElement | null>;
  onSubmit: () => void;
  onContinue: () => void;
}) {
  const adding = Boolean(batch && batch.active > 0);
  const partial = Boolean(batch?.done && batch.failed > 0 && batch.accepted > 0);
  const failed = Boolean(batch?.done && batch.failed > 0 && batch.accepted === 0);
  const showButton = staged > 0 || adding || succeeded;
  return (
    <div className="flex flex-col gap-3">
      {showButton ? (
        <div className="flex flex-wrap items-center gap-3">
          <Button
            data-testid="add-files"
            loading={adding && staged === 0}
            disabled={succeeded}
            leadingIcon={succeeded ? <Icon name="checkCircle" size={16} /> : undefined}
            onClick={() => staged > 0 && onSubmit()}
          >
            {succeeded && batch ? PROVISIONAL.addedTitle(batch.accepted) : adding && staged === 0 ? PROVISIONAL.adding(batch!.active) : PROVISIONAL.addFiles(staged)}
          </Button>
          {staged > 0 ? <p className="text-body-sm text-fg-secondary">{adding ? PROVISIONAL.stagedCount(staged) : PROVISIONAL.addHint}</p> : null}
        </div>
      ) : null}
      <div ref={outcomeRef} tabIndex={-1} role="status" aria-live="polite" className="outline-none empty:hidden">
        {succeeded && batch ? <Notice tone="info" title={PROVISIONAL.addedTitle(batch.accepted)} body={PROVISIONAL.addedBody} /> : null}
        {partial && batch ? (
          <div className="flex flex-col items-start gap-3">
            <Notice tone="warning" title={PROVISIONAL.partialTitle(batch.accepted, batch.failed)} body={PROVISIONAL.partialBody} />
            <Button variant="secondary" onClick={onContinue}>
              {PROVISIONAL.continueWithUploaded}
            </Button>
          </div>
        ) : null}
        {failed && batch ? <Notice tone="warning" title={PROVISIONAL.failedTitle(batch.failed)} body={PROVISIONAL.failedBody} /> : null}
      </div>
    </div>
  );
}

/**
 * Asks before leaving while files are staged or uploading: an accessible dialog for links inside the app, the browser's
 * own prompt for reloads and closing the tab. Inactive when nothing would be lost.
 */
function LeaveGuard({ active, staged }: { active: boolean; staged: number }) {
  const router = useRouter();
  const [target, setTarget] = useState<string | null>(null);
  const stay = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!active) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    const onClick = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const link = (event.target as Element | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
      if (!link || link.target === "_blank" || link.hasAttribute("download")) return;
      const url = new URL(link.href, window.location.href);
      if (url.origin !== window.location.origin) return;
      if (url.pathname === window.location.pathname && url.search === window.location.search) return;
      event.preventDefault();
      event.stopPropagation();
      setTarget(`${url.pathname}${url.search}${url.hash}`);
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    document.addEventListener("click", onClick, true);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      document.removeEventListener("click", onClick, true);
    };
  }, [active]);

  return (
    <Modal
      open={target !== null}
      initialFocus={stay}
      title={PROVISIONAL.leaveTitle}
      description={staged > 0 ? PROVISIONAL.leaveStaged(staged) : PROVISIONAL.leaveUploading}
      onClose={() => setTarget(null)}
      footer={
        <>
          <Button ref={stay} variant="secondary" onClick={() => setTarget(null)}>
            {PROVISIONAL.stay}
          </Button>
          <Button
            variant="danger"
            onClick={() => {
              const href = target;
              setTarget(null);
              if (href) router.push(href);
            }}
          >
            {PROVISIONAL.leave}
          </Button>
        </>
      }
    />
  );
}
