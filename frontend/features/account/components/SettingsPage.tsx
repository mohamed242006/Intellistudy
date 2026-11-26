"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "@/design-system/components/Button";
import { Input } from "@/design-system/components/Input";
import { Modal } from "@/design-system/components/Modal";
import { useToast } from "@/design-system/components/Toast";
import { FormAlert } from "@/features/auth/components/FormAlert";
import { messageFor } from "@/features/auth/messages";
import { signUpSchema } from "@/features/auth/schemas";
import { ApiError } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth/auth-provider";
import { changePassword, logoutAll } from "../api";
import { FIGMA, PROVISIONAL } from "../strings";

/** The new password follows the same policy as sign-up (backend core/passwords.check_policy); the backend decides. */
const passwordSchema = z
  .object({
    current: z.string().min(1, PROVISIONAL.currentPassword).max(1024),
    next: signUpSchema.shape.password,
    confirm: z.string(),
  })
  .refine((v) => v.next === v.confirm, { path: ["confirm"], message: PROVISIONAL.mismatch })
  .refine((v) => v.next !== v.current, { path: ["next"], message: PROVISIONAL.samePassword });

type PasswordValues = z.infer<typeof passwordSchema>;

/** Settings (spec §3.14, 760 content column): only what the backend supports. */
export function SettingsPage() {
  return (
    <div className="mx-auto flex w-full max-w-[808px] flex-col gap-6 px-4 py-8 md:px-6 lg:px-12 lg:py-10">
      <header className="motion-enter flex flex-col gap-2">
        <h1 className="text-h1 text-fg">{FIGMA.title}</h1>
        <p className="text-body text-fg-secondary">{PROVISIONAL.subtitle}</p>
      </header>
      <div className="motion-stagger flex flex-col gap-6">
        <ProfileCard />
        <PasswordCard />
        <SessionsCard />
      </div>
    </div>
  );
}

function Card({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section aria-labelledby={id} className="flex flex-col gap-4 rounded-xl border border-line bg-surface p-4 sm:p-6">
      <h2 id={id} className="text-h3 text-fg">
        {title}
      </h2>
      {children}
    </section>
  );
}

function ProfileCard() {
  const { user } = useAuth();
  return (
    <Card id="settings-profile" title={FIGMA.profile}>
      <dl className="grid gap-4 sm:grid-cols-2">
        <div className="flex min-w-0 flex-col gap-1">
          <dt className="text-label text-fg-secondary">{FIGMA.fullName}</dt>
          <dd className="text-body wrap-anywhere text-fg">{user?.name ?? ""}</dd>
        </div>
        <div className="flex min-w-0 flex-col gap-1">
          <dt className="text-label text-fg-secondary">{FIGMA.email}</dt>
          <dd className="text-body wrap-anywhere text-fg">{user?.email ?? ""}</dd>
        </div>
      </dl>
      <p className="text-caption text-fg-secondary">{PROVISIONAL.profileNote}</p>
    </Card>
  );
}

function PasswordCard() {
  const toast = useToast();
  const [failure, setFailure] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<PasswordValues>({ resolver: zodResolver(passwordSchema), mode: "onBlur", reValidateMode: "onChange" });

  const onSubmit = handleSubmit(async ({ current, next }) => {
    setFailure(null);
    try {
      await changePassword(current, next);
      reset();
      toast(PROVISIONAL.changed, "success");
    } catch (error) {
      if (error instanceof ApiError && error.code === "invalid_current_password") {
        setError("current", { message: PROVISIONAL.wrongCurrent });
      } else if (error instanceof ApiError && error.code === "weak_password") {
        setError("next", { message: error.userMessage ?? PROVISIONAL.failed });
      } else {
        setFailure(error instanceof ApiError && error.kind === "rate_limited" ? PROVISIONAL.rateLimited : messageFor(error).message);
      }
    }
  });

  return (
    <Card id="settings-password" title={PROVISIONAL.password}>
      <p className="text-body-sm text-fg-secondary">{PROVISIONAL.passwordIntro}</p>
      <form noValidate onSubmit={onSubmit} aria-busy={isSubmitting || undefined} className="flex max-w-[480px] flex-col gap-4">
        <FormAlert message={failure} tone="warning" />
        <Input label={PROVISIONAL.currentPassword} type="password" autoComplete="current-password" error={errors.current?.message} {...register("current")} />
        <Input
          label={PROVISIONAL.newPassword}
          type="password"
          autoComplete="new-password"
          helper={PROVISIONAL.newPasswordHelper}
          error={errors.next?.message}
          {...register("next")}
        />
        <Input label={PROVISIONAL.confirmPassword} type="password" autoComplete="new-password" error={errors.confirm?.message} {...register("confirm")} />
        <div>
          <Button type="submit" loading={isSubmitting}>
            {PROVISIONAL.changePassword}
          </Button>
        </div>
      </form>
    </Card>
  );
}

function SessionsCard() {
  const { signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const cancel = useRef<HTMLButtonElement>(null);

  const confirm = async () => {
    if (busy) return;
    setBusy(true);
    setFailure(null);
    try {
      await logoutAll();
      await signOut(); // forget the session here and in other tabs; the app returns to sign-in
    } catch (error) {
      setFailure(messageFor(error).message);
      setBusy(false);
    }
  };

  return (
    <Card id="settings-sessions" title={PROVISIONAL.sessions}>
      <p className="text-body-sm text-fg-secondary">{PROVISIONAL.sessionsIntro}</p>
      <div>
        <Button variant="secondary" onClick={() => setOpen(true)}>
          {PROVISIONAL.logoutAll}
        </Button>
      </div>
      <Modal
        open={open}
        busy={busy}
        initialFocus={cancel}
        title={PROVISIONAL.logoutAllTitle}
        description={PROVISIONAL.logoutAllBody}
        onClose={() => !busy && setOpen(false)}
        footer={
          <>
            <Button ref={cancel} variant="secondary" disabled={busy} onClick={() => setOpen(false)}>
              {PROVISIONAL.cancel}
            </Button>
            <Button variant="danger" loading={busy} onClick={() => void confirm()}>
              {PROVISIONAL.logoutAll}
            </Button>
          </>
        }
      >
        <FormAlert message={failure} tone="warning" />
      </Modal>
    </Card>
  );
}
