"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { BrandMark } from "@/design-system/compositions/Wordmark";
import { Button } from "@/design-system/components/Button";
import { ChatComposer } from "@/design-system/components/ChatComposer";
import { EmptyState } from "@/design-system/components/EmptyState";
import { Modal } from "@/design-system/components/Modal";
import { Notice } from "@/design-system/components/Notice";
import { useToast } from "@/design-system/components/Toast";
import { Breadcrumb } from "@/design-system/compositions/Breadcrumb";
import { Icon } from "@/design-system/icons/Icon";
import { CourseNotFound } from "@/features/courses/components/CourseNotFound";
import { useCourse } from "@/features/courses/hooks";
import { FIGMA as COURSE_FIGMA } from "@/features/courses/strings";
import { useDocuments } from "@/features/documents/hooks";
import { FormAlert } from "@/features/auth/components/FormAlert";
import { ResourceNotFound } from "@/features/shell/components/ResourceNotFound";
import { SourceView } from "@/features/sources/SourceView";
import { FIGMA as SOURCE_FIGMA } from "@/features/sources/strings";
import { ApiError } from "@/lib/api/errors";
import type { ConversationOut, MessageOut } from "@/lib/api/types";
import { relativeTime } from "@/lib/format/format";
import { useNow } from "@/lib/format/use-now";
import { useRetryAfter, waitPhrase } from "@/lib/hooks/use-retry-after";
import { useConversation, useConversations, useCreateConversation, useDeleteConversation, useSendMessage } from "../hooks";
import { FIGMA, PROVISIONAL, SEND_ERRORS } from "../strings";
import { takeHandoff } from "@/features/documents/handoff";
import { starterQuestions } from "../clarify";
import { AssistantMessage, PendingAnswer, UserBubble, type ChatContext } from "./ChatMessage";

export const MAX_QUESTION_CHARS = 2000;
const CANONICAL_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/** `?c=`: only a canonical id is requested; anything else is "not found" without a request (GF1-17). */
export function parseConversationParam(raw: string | null): { id: string | null; invalid: boolean } {
  if (raw === null || raw === "") return { id: null, invalid: false };
  return CANONICAL_ID.test(raw) ? { id: raw, invalid: false } : { id: null, invalid: true };
}

/** Client check mirroring backend normalize_question: whitespace collapsed and trimmed, then 1-2000 characters. */
export function questionProblem(raw: string): "empty" | "too_long" | null {
  const text = raw.replace(/\s+/g, " ").trim();
  if (!text) return "empty";
  if (Array.from(text).length > MAX_QUESTION_CHARS) return "too_long";
  return null;
}

export function sendErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return SEND_ERRORS.fallback;
  if (error.code === "invalid_question" || error.code === "validation_error") return SEND_ERRORS.invalid_question;
  if (error.code === "token_budget") return SEND_ERRORS.token_budget;
  if (error.code === "rate_limited") return SEND_ERRORS.rate_limited(error.retryAfterSeconds === null ? "in a moment" : waitPhrase(error.retryAfterSeconds));
  if (error.kind === "network") return SEND_ERRORS.network;
  if (error.kind === "not_found") return SEND_ERRORS.not_found;
  if (error.kind === "session_expired") return SEND_ERRORS.session_expired;
  return SEND_ERRORS.fallback;
}

/** The conversation to fall back to after deleting `removed`: the next one in the list, else the previous one. */
export function neighbourAfterDelete(list: readonly ConversationOut[], removed: string): string | null {
  const index = list.findIndex((c) => c.id === removed);
  const rest = list.filter((c) => c.id !== removed);
  if (rest.length === 0) return null;
  return (rest[Math.min(Math.max(index, 0), rest.length - 1)] ?? rest[0]!).id;
}

/**
 * Chat (UI §8.6; gates GF1-11..18, GF1-20..24). The conversation list (not drawn in Figma) is a provisional column;
 * the selected conversation lives in `?c=`. Answers are only what the backend returned for this conversation.
 */
export function ChatPage({ courseId }: { courseId: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const now = useNow();
  const toast = useToast();
  const course = useCourse(courseId);
  const conversations = useConversations(courseId, { enabled: course.isSuccess });
  const documents = useDocuments(courseId, { poll: false, enabled: course.isSuccess });
  const create = useCreateConversation(courseId);
  const remove = useDeleteConversation(courseId);
  const [deleting, setDeleting] = useState(false);
  const deleteCancel = useRef<HTMLButtonElement>(null);
  // "Ask selected materials" from the workspace: answers come only from those files until the reader widens the scope.
  const [scopeIds, setScopeIds] = useState<string[]>(() => (params.get("from") === "workspace" ? takeHandoff(courseId, "chat") : []));

  const { id: requested, invalid } = parseConversationParam(params.get("c"));
  const list = conversations.data?.pages.flatMap((p) => p.items) ?? [];
  const firstId = list[0]?.id ?? null;
  const allReady = documents.documents.filter((d) => d.status === "ready").map((d) => ({ id: d.id, file_name: d.file_name }));
  const scoped = scopeIds.filter((id) => allReady.some((d) => d.id === id));
  const ready = scoped.length ? allReady.filter((d) => scoped.includes(d.id)) : allReady;
  const readyFiles = ready.length;

  // No `?c`: open the most recently active conversation (the backend lists them newest first).
  useEffect(() => {
    if (!requested && !invalid && conversations.isSuccess && firstId) router.replace(`${pathname}?c=${encodeURIComponent(firstId)}`, { scroll: false });
  }, [requested, invalid, conversations.isSuccess, firstId, pathname, router]);

  if (course.isError && course.error instanceof ApiError && course.error.kind === "not_found") return <CourseNotFound />;
  if (course.isPending) return <div aria-busy="true" role="status" aria-label={PROVISIONAL.conversations} className="min-h-[50vh]" />;
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

  const open = (id: string) => router.push(`${pathname}?c=${encodeURIComponent(id)}`, { scroll: false });
  const newConversation = () => {
    if (create.isPending) return;
    create.mutate(undefined, { onSuccess: (c) => open(c.id) });
  };

  return (
    <div className="grid min-h-screen grid-cols-1 lg:grid-cols-[300px_minmax(0,1fr)]">
      <section aria-labelledby="conversations-heading" className="flex min-w-0 flex-col gap-4 border-line px-4 py-6 md:px-8 lg:border-r lg:px-4">
        <h2 id="conversations-heading" className="text-title text-fg">
          {PROVISIONAL.conversations}
        </h2>
        <Button variant="secondary" fullWidth loading={create.isPending} onClick={newConversation}>
          {FIGMA.newConversation}
        </Button>
        {conversations.isPending ? <div aria-busy="true" role="status" aria-label={PROVISIONAL.conversations} className="h-20" /> : null}
        {conversations.isError && list.length === 0 ? (
          <div role="alert" className="flex flex-col items-start gap-3">
            <Notice tone="warning" title={PROVISIONAL.loadError} />
            <Button variant="secondary" onClick={() => void conversations.refetch()}>
              {PROVISIONAL.tryAgain}
            </Button>
          </div>
        ) : null}
        <ul className="flex flex-col gap-1">
          {list.map((c) => {
            const current = c.id === requested;
            return (
              <li key={c.id}>
                <Link
                  href={`${pathname}?c=${encodeURIComponent(c.id)}`}
                  scroll={false}
                  aria-current={current ? "true" : undefined}
                  className={`flex min-h-11 flex-col justify-center rounded-md border px-3 py-2 ${current ? "border-accent-subtle-border bg-accent-subtle" : "border-transparent hover:bg-subtle"}`}
                >
                  <span className="text-label break-words text-fg">{c.title}</span>
                  <span className="text-caption text-fg-secondary">{PROVISIONAL.updated(relativeTime(c.updated_at, now))}</span>
                </Link>
              </li>
            );
          })}
        </ul>
        {conversations.hasNextPage ? (
          <Button variant="secondary" loading={conversations.isFetchingNextPage} onClick={() => void conversations.fetchNextPage()}>
            {PROVISIONAL.showMore}
          </Button>
        ) : null}
      </section>

      <div className="flex min-w-0 flex-col">
        <header className="flex flex-col gap-4 border-b border-line px-4 pt-6 pb-4 md:px-8 lg:px-10">
          <Breadcrumb items={[{ label: COURSE_FIGMA.courses, href: "/#courses" }, { label: course.data.name, href: `/courses/${encodeURIComponent(courseId)}` }, { label: "Chat" }]} />
          <div className="flex flex-wrap items-start justify-between gap-4">
            <h1 className="min-w-0 text-h2 break-words text-fg">{course.data.name}</h1>
            {requested ? (
              <Button variant="secondary" onClick={() => setDeleting(true)}>
                {PROVISIONAL.deleteConversation}
              </Button>
            ) : null}
          </div>
        </header>
        {invalid ? (
          <ResourceNotFound />
        ) : requested ? (
          <Conversation
            key={requested}
            courseId={courseId}
            conversationId={requested}
            readyFiles={documents.isSuccess ? readyFiles : null}
            files={ready}
            scopeIds={scoped}
            onWidenScope={() => setScopeIds([])}
          />
        ) : conversations.isSuccess && list.length === 0 ? (
          <div className="px-4 py-10">
            <EmptyState
              size="page"
              icon="message"
              title={PROVISIONAL.emptyTitle}
              body={PROVISIONAL.emptyBody}
              action={
                <Button loading={create.isPending} onClick={newConversation}>
                  {FIGMA.newConversation}
                </Button>
              }
            />
          </div>
        ) : null}
      </div>

      <Modal
        open={deleting}
        busy={remove.isPending}
        initialFocus={deleteCancel}
        title={PROVISIONAL.deleteTitle}
        description={PROVISIONAL.deleteBody}
        onClose={() => setDeleting(false)}
        footer={
          <>
            <Button ref={deleteCancel} variant="secondary" disabled={remove.isPending} onClick={() => setDeleting(false)}>
              {PROVISIONAL.cancel}
            </Button>
            <Button
              variant="danger"
              loading={remove.isPending}
              onClick={() => {
                if (!requested || remove.isPending) return;
                const neighbour = neighbourAfterDelete(list, requested);
                remove.mutate(requested, {
                  onSuccess: () => {
                    setDeleting(false);
                    toast(PROVISIONAL.conversationDeleted, "success");
                    router.replace(neighbour ? `${pathname}?c=${encodeURIComponent(neighbour)}` : pathname, { scroll: false });
                  },
                })
              }}
            >
              {PROVISIONAL.deleteConversation}
            </Button>
          </>
        }
      >
        <FormAlert message={remove.isError ? SEND_ERRORS.fallback : null} />
      </Modal>
    </div>
  );
}

/** One conversation: history, the pending exchange, the composer and this conversation's source selection. */
function Conversation({ courseId, conversationId, readyFiles, files, scopeIds = [], onWidenScope }: {
  courseId: string;
  conversationId: string;
  readyFiles: number | null;
  files: ReadonlyArray<{ id: string; file_name: string }>;
  /** Ready files the questions are limited to (empty: every ready file of the course). */
  scopeIds?: readonly string[];
  onWidenScope?: () => void;
}) {
  const detail = useConversation(conversationId);
  const send = useSendMessage(courseId, conversationId, scopeIds);
  const retryAfter = useRetryAfter();
  const toast = useToast();
  const [draft, setDraft] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  /** The last send failed for a reason worth retrying as is (network, server): offer "Send again". */
  const [canResend, setCanResend] = useState(false);
  const [selected, setSelected] = useState<{ messageId: string; number: number } | null>(null);
  const trigger = useRef<HTMLElement | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const count = detail.data?.messages.length ?? 0;

  // Keep the newest exchange in view when one is sent or arrives (instant under reduced motion).
  useEffect(() => {
    if (count === 0 && !send.isPending) return;
    const reduce = typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    end.current?.scrollIntoView?.({ block: "end", behavior: reduce ? "auto" : "smooth" });
  }, [count, send.isPending]);

  if (detail.isError && detail.error instanceof ApiError && detail.error.kind === "not_found") return <ResourceNotFound />;
  if (detail.data && detail.data.course_id !== courseId) return <ResourceNotFound />; // a conversation of another course
  if (detail.isPending) return <div aria-busy="true" role="status" aria-label={PROVISIONAL.messages} className="h-40" />;
  if (detail.isError) {
    return (
      <div role="alert" className="flex flex-col items-start gap-4 px-4 py-10 md:px-8 lg:px-10">
        <Notice tone="warning" title={PROVISIONAL.conversationError} />
        <Button variant="secondary" onClick={() => void detail.refetch()}>
          {PROVISIONAL.tryAgain}
        </Button>
      </div>
    );
  }

  const messages = detail.data.messages;
  const owner: MessageOut | undefined = selected ? messages.find((m) => m.id === selected.messageId) : undefined;
  const submit = () => {
    if (send.isPending || retryAfter.blocked) return;
    const issue = questionProblem(draft);
    if (issue) {
      setProblem(issue === "empty" ? PROVISIONAL.questionEmpty : PROVISIONAL.questionTooLong);
      return;
    }
    setProblem(null);
    setCanResend(false);
    send.mutate(draft, {
      onSuccess: () => setDraft(""), // cleared only after the backend stored the exchange
      onError: (error) => {
        retryAfter.note(error);
        setProblem(sendErrorMessage(error));
        setCanResend(!(error instanceof ApiError) || error.kind === "network" || error.status >= 500);
      },
    });
  };
  const context: ChatContext = {
    courseId,
    files,
    onSuggest: (text) => {
      setDraft(text);
      setProblem(null);
      const field = input.current;
      if (field) {
        field.focus();
        requestAnimationFrame(() => field.setSelectionRange(text.length, text.length));
      }
    },
    onCopy: (text) => {
      const clipboard = typeof navigator !== "undefined" ? navigator.clipboard : undefined;
      if (!clipboard) {
        toast(PROVISIONAL.copyFailed, "warning");
        return;
      }
      clipboard.writeText(text).then(
        () => toast(PROVISIONAL.copied, "success"),
        () => toast(PROVISIONAL.copyFailed, "warning"),
      );
    },
  };
  const starters = starterQuestions(files.map((f) => f.file_name));

  return (
    <div className="flex min-w-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col">
        {/* role="log" on a wrapper: on the <ol> itself it would remove the list semantics of the exchanges */}
        <div role="log" aria-label={PROVISIONAL.messages} className="mx-auto flex w-full max-w-[760px] flex-1 flex-col px-4 py-8 md:px-8 lg:py-10">
        <ol className="flex flex-col gap-8">
          {messages.length === 0 && !send.isPending ? (
            <li className="motion-enter flex flex-col items-start gap-4">
              <div className="flex items-center gap-3">
                <BrandMark size={32} />
                <p className="text-body text-fg-secondary">{PROVISIONAL.emptyConversation}</p>
              </div>
              {starters.length ? (
                <div className="flex flex-col gap-2">
                  <p className="text-caption-strong text-fg-secondary">{PROVISIONAL.starters}</p>
                  <ul className="flex flex-col gap-2">
                    {starters.map((text) => (
                      <li key={text}>
                        <button
                          type="button"
                          onClick={() => context.onSuggest(text)}
                          className="min-h-11 max-w-full rounded-lg border border-line bg-surface px-4 py-2 text-left text-body-sm wrap-anywhere text-fg hover:border-line-strong hover:bg-subtle"
                        >
                          {text}
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </li>
          ) : null}
          {messages.map((message) => (
            <li key={message.id} className="flex flex-col gap-4" data-message={message.id}>
              <UserBubble text={message.question} />
              <AssistantMessage
                context={context}
                message={message}
                activeNumber={selected?.messageId === message.id ? selected.number : null}
                onSelect={(number, from) => {
                  trigger.current = from;
                  setSelected({ messageId: message.id, number });
                }}
              />
            </li>
          ))}
          {send.isPending ? (
            <li className="flex flex-col gap-4">
              <UserBubble text={send.variables ?? ""} />
              <PendingAnswer searching={readyFiles === null ? FIGMA.loadingPlaceholder : FIGMA.searching(readyFiles)} />
            </li>
          ) : null}
        </ol>
        <div ref={end} />
        </div>
        <div className="sticky bottom-0 flex flex-col gap-2 border-t border-line bg-canvas px-4 pt-4 pb-6 md:px-8 lg:px-10">
          <div className="mx-auto flex w-full max-w-[760px] flex-col gap-2">
            {readyFiles === 0 ? <Notice tone="info" title={PROVISIONAL.noReadyFiles} /> : null}
            <ChatComposer
              label={FIGMA.composerLabel}
              value={draft}
              onChange={(value) => {
                setDraft(value);
                if (problem && questionProblem(value) === null) setProblem(null);
              }}
              onSubmit={submit}
              pending={send.isPending}
              blocked={retryAfter.blocked}
              placeholder={FIGMA.placeholder}
              loadingPlaceholder={FIGMA.loadingPlaceholder}
              sendLabel={FIGMA.send}
              pendingLabel={FIGMA.answering}
              scope={readyFiles === null ? null : scopeIds.length ? PROVISIONAL.scopedTo(scopeIds.length) : FIGMA.scope(readyFiles)}
              error={problem}
              maxLength={MAX_QUESTION_CHARS * 2}
              inputRef={input}
              errorAction={
                canResend && !send.isPending && !retryAfter.blocked && draft.trim() ? (
                  <Button variant="secondary" onClick={submit} leadingIcon={<Icon name="retry" size={16} />}>
                    {PROVISIONAL.sendAgain}
                  </Button>
                ) : null
              }
            />
            {scopeIds.length && onWidenScope ? (
              <p className="flex flex-wrap items-center gap-2 text-caption text-fg-secondary">
                <span className="min-w-0 wrap-anywhere">{PROVISIONAL.scopeFiles(files.map((f) => f.file_name))}</span>
                <button type="button" onClick={onWidenScope} className="min-h-11 rounded-md px-2 text-label text-accent-fg hover:bg-accent-subtle">
                  {PROVISIONAL.useAllFiles}
                </button>
              </p>
            ) : null}
            <p className="text-caption text-fg-secondary">{FIGMA.disclaimer}</p>
          </div>
        </div>
      </div>
      <SourceView
        sources={owner?.citations ?? []}
        selected={owner ? selected!.number : null}
        listTitle={SOURCE_FIGMA.allSourcesAnswer}
        showContext
        onSelect={(number, from) => {
          trigger.current = from;
          if (owner) setSelected({ messageId: owner.id, number });
        }}
        onClose={() => setSelected(null)}
        returnFocus={() => trigger.current}
        alwaysShowPanel={false}
      />
    </div>
  );
}
