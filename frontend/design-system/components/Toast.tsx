"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Icon } from "../icons/Icon";
import type { IconName } from "../icons/placeholders";
import { IconButton } from "./IconButton";

/**
 * Toast (UI §7.13, §18 D-16): 440 max, radius 12, padding 4/4/4/16, gap 12, `shadow/md`; tone fill and border; icon 20 +
 * message `text/body-sm` + close IconButton. Bottom centre, stacked 8 px apart, 5 s auto-dismiss (Danger stays).
 * The container is a polite live region that exists before any toast, so additions are announced.
 */
export type ToastTone = "info" | "success" | "warning" | "danger";
type ToastItem = { id: number; tone: ToastTone; message: string };

const TONE: Record<ToastTone, { box: string; icon: IconName }> = {
  info: { box: "bg-accent-subtle border-accent-subtle-border", icon: "info" },
  success: { box: "bg-success-bg border-success-border", icon: "checkCircle" },
  warning: { box: "bg-warning-bg border-warning-border", icon: "alert" },
  danger: { box: "bg-danger-bg border-danger-border", icon: "alert" },
};

export const TOAST_TIMEOUT_MS = 5_000;

const ToastContext = createContext<((message: string, tone?: ToastTone) => void) | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const next = useRef(1);
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());

  const dismiss = useCallback((id: number) => {
    setItems((current) => current.filter((item) => item.id !== id));
    const timer = timers.current.get(id);
    if (timer) clearTimeout(timer);
    timers.current.delete(id);
  }, []);

  const show = useCallback(
    (message: string, tone: ToastTone = "info") => {
      const id = next.current++;
      setItems((current) => [...current.slice(-2), { id, tone, message }]);
      if (tone !== "danger") timers.current.set(id, setTimeout(() => dismiss(id), TOAST_TIMEOUT_MS));
    },
    [dismiss],
  );

  useEffect(() => {
    const pending = timers.current;
    return () => {
      for (const timer of pending.values()) clearTimeout(timer);
      pending.clear();
    };
  }, []);

  const value = useMemo(() => show, [show]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        aria-label="Notifications"
        role="region"
        className="pointer-events-none fixed inset-x-0 bottom-6 z-[60] flex flex-col items-center gap-2 px-4"
      >
        {items.map((item) => (
          <div
            key={item.id}
            role={item.tone === "danger" ? "alert" : "status"}
            data-tone={item.tone}
            className={`pointer-events-auto flex w-[440px] max-w-full items-center gap-3 rounded-lg border py-1 pr-1 pl-4 shadow-md ${TONE[item.tone].box}`}
          >
            <Icon name={TONE[item.tone].icon} size={20} />
            <p className="min-w-0 flex-1 text-body-sm break-words text-fg">{item.message}</p>
            <IconButton icon="x" label="Dismiss notification" onClick={() => dismiss(item.id)} />
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): (message: string, tone?: ToastTone) => void {
  const value = useContext(ToastContext);
  if (!value) throw new Error("useToast must be used inside ToastProvider");
  return value;
}
