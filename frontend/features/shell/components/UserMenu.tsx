"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Button } from "@/design-system/components/Button";
import { Avatar } from "@/design-system/compositions/Avatar";
import { UserCard } from "@/design-system/compositions/UserCard";
import { useAuth } from "@/lib/auth/auth-provider";
import { PROVISIONAL } from "../strings";

/**
 * Account disclosure (plan decision 11.3-5; Figma draws no sign-out). The user card (Sidebar) or the avatar (Rail,
 * top bar) toggles a small panel holding "Sign out". Escape closes it and returns focus to the toggle.
 */
export function UserMenu({ variant }: { variant: "card" | "avatar" }) {
  const { user, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const panelId = useId();
  const toggle = useRef<HTMLButtonElement>(null);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        toggle.current?.focus();
      }
    };
    const onPointer = (event: PointerEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open]);

  if (!user) return null;
  const common = { "aria-expanded": open, "aria-controls": panelId, onClick: () => setOpen((v) => !v) };
  return (
    <div ref={root} className="relative w-full">
      {open ? (
        <div id={panelId} className={`absolute bottom-full z-10 mb-2 flex w-[232px] flex-col gap-2 rounded-lg border border-line bg-raised p-3 shadow-md ${variant === "card" ? "left-0" : "left-0 max-lg:right-0 max-lg:left-auto max-lg:top-full max-lg:bottom-auto max-lg:mt-2"}`}>
          <p className="truncate text-caption text-fg-secondary">{user.email}</p>
          <Button
            variant="secondary"
            fullWidth
            loading={busy}
            onClick={() => {
              setBusy(true);
              void signOut().finally(() => setBusy(false));
            }}
          >
            {PROVISIONAL.signOut}
          </Button>
        </div>
      ) : null}
      {variant === "card" ? (
        <UserCard ref={toggle} name={user.name} subtitle={user.email} namePrefix={PROVISIONAL.account + ":"} {...common} />
      ) : (
        <button ref={toggle} type="button" title={user.name} className="flex size-11 items-center justify-center rounded-full hover:bg-subtle" {...common}>
          <Avatar name={user.name} />
          <span className="sr-only">{PROVISIONAL.accountMenu(user.name)}</span>
        </button>
      )}
    </div>
  );
}
