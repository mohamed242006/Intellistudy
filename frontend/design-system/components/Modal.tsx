"use client";

import { useEffect, useId, useRef, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";
import { IconButton } from "./IconButton";

/**
 * Modal (UI §7.14, §18 D-17): 480 wide, radius 16, `bg/raised`, 1 px `border/default`, `shadow/lg`, padding 24, gap 16;
 * header (Title `text/h3` + close IconButton), body (`text/body` secondary), footer (Cancel + confirm). Centred over a
 * `bg/scrim` 45% scrim.
 *
 * Accessibility (GF0B-03): `role="dialog"` + `aria-modal`, labelled by the title and described by the body; focus moves
 * inside on open (the `initialFocus` element, else the first field or button); Tab and Shift+Tab stay inside; the rest
 * of the page is `inert`; Escape cancels (never confirms) unless an operation is pending; on close, focus returns to
 * the element that opened the dialog. Destructive dialogs start on Cancel, so confirming always takes an explicit press.
 */
const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function Modal({ open, title, description, children, footer, onClose, busy = false, initialFocus, closeLabel = "Close dialog" }: {
  open: boolean;
  title: string;
  description?: string;
  children?: ReactNode;
  footer: ReactNode;
  onClose: () => void;
  /** While true (a request is in flight) Escape and the close button do nothing. */
  busy?: boolean;
  initialFocus?: RefObject<HTMLElement | null>;
  closeLabel?: string;
}) {
  const titleId = useId();
  const bodyId = useId();
  const panel = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  const busyRef = useRef(busy);
  onCloseRef.current = onClose;
  busyRef.current = busy;

  useEffect(() => {
    if (!open) return;
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const host = panel.current?.closest<HTMLElement>("[data-modal-root]") ?? null;
    const siblings = Array.from(document.body.children).filter((el): el is HTMLElement => el instanceof HTMLElement && el !== host && !el.hasAttribute("inert"));
    for (const el of siblings) el.setAttribute("inert", "");

    const target = initialFocus?.current ?? panel.current?.querySelector<HTMLElement>("input, textarea, select") ?? panel.current?.querySelector<HTMLElement>(FOCUSABLE);
    (target ?? panel.current)?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        if (!busyRef.current) onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !panel.current) return;
      const items = Array.from(panel.current.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (items.length === 0) {
        event.preventDefault();
        return;
      }
      const first = items[0]!;
      const last = items[items.length - 1]!;
      const active = document.activeElement;
      if (event.shiftKey && (active === first || !panel.current.contains(active))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active === last || !panel.current.contains(active))) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      for (const el of siblings) el.removeAttribute("inert");
      if (trigger?.isConnected) trigger.focus();
    };
    // initialFocus is read once on open
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  if (!open || typeof document === "undefined") return null;
  return createPortal(
    <div data-modal-root className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div aria-hidden="true" className="absolute inset-0 bg-scrim/45" />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? bodyId : undefined}
        tabIndex={-1}
        className="relative flex max-h-[calc(100vh-32px)] w-[480px] max-w-full flex-col gap-4 overflow-y-auto rounded-xl border border-line bg-raised p-6 shadow-lg outline-none"
      >
        <div className="flex items-start justify-between gap-4">
          <h2 id={titleId} className="pt-2 text-h3 break-words text-fg">
            {title}
          </h2>
          <IconButton icon="x" label={closeLabel} onClick={() => !busy && onClose()} disabled={busy} />
        </div>
        {description ? (
          <p id={bodyId} className="text-body break-words text-fg-secondary">
            {description}
          </p>
        ) : null}
        {children}
        <div className="flex flex-wrap justify-end gap-3">{footer}</div>
      </div>
    </div>,
    document.body,
  );
}
