"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Button } from "@/design-system/components/Button";
import { Input } from "@/design-system/components/Input";
import { useAuth } from "@/lib/auth/auth-provider";
import { messageFor } from "../messages";
import { signInSchema, type SignInValues } from "../schemas";
import { BACKEND, FIGMA, PROVISIONAL } from "../strings";
import { FormAlert } from "./FormAlert";

export function SignInForm() {
  const { signIn, endReason } = useAuth();
  const [failure, setFailure] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<SignInValues>({ resolver: zodResolver(signInSchema), mode: "onBlur", reValidateMode: "onChange" });

  const onSubmit = handleSubmit(async ({ email, password }) => {
    setFailure(null);
    try {
      await signIn(email, password); // the auth layout navigates once the session exists
    } catch (error) {
      setFailure(messageFor(error).message); // one generic message for any credential problem (no account hint)
    }
  });

  const notice = failure ?? (endReason === "expired" ? BACKEND.sessionExpired : endReason === "signed-out" ? PROVISIONAL.signedOut : null);

  return (
    <>
      <h1 className="text-h2 text-fg">{FIGMA.signInTitle}</h1>
      <form noValidate onSubmit={onSubmit} aria-busy={isSubmitting || undefined} className="flex flex-col gap-6">
        <FormAlert message={notice} tone={failure ? "warning" : "info"} />
        <Input
          label={FIGMA.emailLabel}
          type="email"
          autoComplete="email"
          inputMode="email"
          placeholder={FIGMA.emailPlaceholder}
          helper={FIGMA.emailHelper}
          error={errors.email?.message}
          {...register("email")}
        />
        <Input
          label={FIGMA.passwordLabel}
          type="password"
          autoComplete="current-password"
          placeholder={FIGMA.passwordPlaceholderSignIn}
          error={errors.password?.message}
          {...register("password")}
        />
        <Button type="submit" variant="primary" fullWidth loading={isSubmitting}>
          {FIGMA.signInButton}
        </Button>
        <p className="text-center">
          <button
            type="button"
            disabled
            aria-describedby="reset-unavailable"
            className="text-body-sm text-fg-link disabled:cursor-not-allowed"
          >
            {FIGMA.forgotPassword}
          </button>
          <span id="reset-unavailable" className="sr-only">
            {PROVISIONAL.resetUnavailable}
          </span>
        </p>
      </form>
    </>
  );
}

