/**
 * Client-side validation mirroring the backend (gate GF0A-06). The backend stays authoritative: it alone rejects
 * common passwords and existing accounts. There is no `.edu` rule because the backend has none.
 *
 *   RegisterRequest: email 3-320, name 1-200 (1-100 after whitespace normalisation), password checked by
 *   core/passwords.check_policy: 10-128 characters, a letter, a digit. Email pattern: services/auth.py _EMAIL.
 *   LoginRequest: email 1-320, password 1-1024.
 */

import { z } from "zod";
import { BACKEND, PROVISIONAL } from "./strings";

const EMAIL_PATTERN = /^[^@\s]{1,64}@[^@\s]+\.[^@\s]+$/;
const LETTER = /\p{L}/u;
const DIGIT = /\p{Nd}/u;

export const normaliseName = (name: string): string => name.normalize("NFKC").split(/\s+/).filter(Boolean).join(" ");

const signUpEmail = z
  .string()
  .trim()
  .max(320, BACKEND.invalidEmail)
  .refine((value) => value.length <= 254 && EMAIL_PATTERN.test(value.toLowerCase()), BACKEND.invalidEmail);

export const signUpSchema = z.object({
  name: z
    .string()
    .max(200, BACKEND.invalidName)
    .refine((value) => {
      const clean = normaliseName(value);
      return clean.length >= 1 && clean.length <= 100;
    }, BACKEND.invalidName),
  email: signUpEmail,
  password: z
    .string()
    .min(10, BACKEND.passwordTooShort)
    .max(128, BACKEND.passwordTooLong)
    .refine((value) => LETTER.test(value), BACKEND.passwordNeedsLetter)
    .refine((value) => DIGIT.test(value), BACKEND.passwordNeedsDigit),
});

export const signInSchema = z.object({
  email: z.string().trim().min(1, PROVISIONAL.emailRequired).max(320, BACKEND.invalidEmail),
  password: z.string().min(1, PROVISIONAL.passwordRequired).max(1024, BACKEND.invalidCredentials),
});

export type SignUpValues = z.infer<typeof signUpSchema>;
export type SignInValues = z.infer<typeof signInSchema>;
