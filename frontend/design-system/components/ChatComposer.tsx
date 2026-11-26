"use client";

import { useId, type KeyboardEvent, type Ref } from "react";
import { Icon } from "../icons/Icon";
import { Button } from "./Button";

/**
 * ChatComposer (UI §7.20): V, padding 12/12/12/16, gap 8, radius 16, `bg/surface`, 1 px `border/strong`; a labelled
 * `<textarea>` (`text/body`) and a toolbar (scope icon 16 + scope caption + Primary Send 44 high). Loading: the
 * placeholder becomes "Searching your materials…" and the button "Answering…" (`aria-busy`), the text stays readable
 * but read-only. Enter sends, Shift+Enter adds a line (UI §18 D-7); nothing is sent while composing an IME word.
 */
export function ChatComposer({ label, value, onChange, onSubmit, pending, blocked, placeholder, loadingPlaceholder, sendLabel, pendingLabel, scope, error, maxLength, inputRef, errorAction }: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  pending: boolean;
  /** Sending is not allowed now (for example until Retry-After passes); the text stays editable. */
  blocked: boolean;
  placeholder: string;
  loadingPlaceholder: string;
  sendLabel: string;
  pendingLabel: string;
  scope: string | null;
  error: string | null;
  maxLength: number;
  /** The textarea, so a suggestion can put a question in and focus it. */
  inputRef?: Ref<HTMLTextAreaElement>;
  /** Shown next to the error, for example "Send again" after a network failure. */
  errorAction?: React.ReactNode;
}) {
  const id = useId();
  const errorId = `${id}-error`;
  const submit = () => {
    if (!pending && !blocked) onSubmit();
  };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };
  return (
    <form
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
      className="flex flex-col gap-2"
    >
      <div className="flex flex-col gap-2 rounded-xl border border-line-strong bg-surface py-3 pr-3 pl-4 focus-within:outline-2 focus-within:outline-focus-ring">
        <label htmlFor={id} className="sr-only">
          {label}
        </label>
        <textarea
          ref={inputRef}
          id={id}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={onKeyDown}
          rows={2}
          maxLength={maxLength}
          readOnly={pending}
          aria-busy={pending || undefined}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : undefined}
          placeholder={pending ? loadingPlaceholder : placeholder}
          className={`min-h-12 w-full resize-none bg-transparent text-body outline-none placeholder:text-fg-tertiary focus-visible:outline-none ${pending ? "text-disabled-fg" : "text-fg"}`}
        />
        <div className="flex flex-wrap items-center gap-2">
          {scope ? (
            <span className="flex min-w-0 flex-1 items-center gap-1 text-caption text-fg-secondary">
              <Icon name="search" size={16} />
              <span className="min-w-0">{scope}</span>
            </span>
          ) : (
            <span className="flex-1" />
          )}
          <Button type="submit" loading={pending} disabled={blocked} leadingIcon={<Icon name="send" size={16} />}>
            {pending ? pendingLabel : sendLabel}
          </Button>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <p id={errorId} role="alert" className="text-body-sm text-danger-fg empty:sr-only">
          {error ?? ""}
        </p>
        {error && errorAction ? errorAction : null}
      </div>
    </form>
  );
}
