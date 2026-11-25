"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Button } from "@/design-system/components/Button";
import { Input } from "@/design-system/components/Input";
import { useAuth } from "@/lib/auth/auth-provider";
import { messageFor } from "../messages";
import { signUpSchema, type SignUpValues } from "../schemas";
import { BACKEND_ALIGNED, FIGMA } from "../strings";
import { FormAlert } from "./FormAlert";

export function SignUpForm() {
  const { signUp } = useAuth();
  const [failure, setFailure] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<SignUpValues>({ resolver: zodResolver(signUpSchema), mode: "onBlur", reValidateMode: "onChange" });

  const onSubmit = handleSubmit(async ({ name, email, password }) => {
    setFailure(null);
    try {
      await signUp(name, email, password); // register, then sign in; the password is never stored
    } catch (error) {
      const { field, message } = messageFor(error);
      if (field) setError(field, { type: "server", message }, { shouldFocus: true });
      else setFailure(message);
    }
  });

  return (
    <>
      <h1 className="text-h2 text-fg">{FIGMA.signUpTitle}</h1>
      <form noValidate onSubmit={onSubmit} aria-busy={isSubmitting || undefined} className="flex flex-col gap-6">
        <FormAlert message={failure} />
        <Input label={FIGMA.fullNameLabel} autoComplete="name" error={errors.name?.message} {...register("name")} />
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
          autoComplete="new-password"
          placeholder={BACKEND_ALIGNED.passwordPlaceholderSignUp}
          helper={BACKEND_ALIGNED.passwordHelperSignUp}
          error={errors.password?.message}
          {...register("password")}
        />
        <Button type="submit" variant="primary" fullWidth loading={isSubmitting}>
          {FIGMA.createAccountButton}
        </Button>
        <p className="text-body-sm text-fg-secondary">{FIGMA.legal}</p>
      </form>
    </>
  );
}
