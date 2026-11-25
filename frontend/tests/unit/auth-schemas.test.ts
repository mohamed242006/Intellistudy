import { describe, expect, it } from "vitest";
import { signInSchema, signUpSchema } from "@/features/auth/schemas";

const ok = { name: "Test Student", email: "student@example.org", password: "lectures4ever" };
const messages = (value: unknown) => {
  const result = signUpSchema.safeParse(value);
  return result.success ? [] : result.error.issues.map((i) => i.message);
};

describe("GF0A-06 auth validation mirrors the backend", () => {
  it("GF0A-06 sign-up password: 10-128 characters with a letter and a digit (no 12-character rule)", () => {
    expect(messages(ok)).toEqual([]);
    expect(messages({ ...ok, password: "abc123def" })).toContain("Password must be at least 10 characters.");
    expect(messages({ ...ok, password: "abcd1234ef" })).toEqual([]);
    expect(messages({ ...ok, password: "a1".repeat(65) })).toContain("Password must be at most 128 characters.");
    expect(messages({ ...ok, password: "1234567890" })).toContain("Password must contain at least one letter.");
    expect(messages({ ...ok, password: "abcdefghij" })).toContain("Password must contain at least one digit.");
  });

  it("GF0A-06 sign-up email follows the backend pattern and has no .edu rule", () => {
    expect(messages({ ...ok, email: "someone@gmail.com" })).toEqual([]);
    for (const bad of ["no-at-sign", "a@b", "two words@x.org", `${"x".repeat(65)}@example.org`]) {
      expect(messages({ ...ok, email: bad }), bad).toContain("Enter a valid email address.");
    }
  });

  it("GF0A-06 sign-up name is 1-100 characters after whitespace normalisation", () => {
    expect(messages({ ...ok, name: "   " })).toContain("Enter your name (1-100 characters).");
    expect(messages({ ...ok, name: "x".repeat(101) })).toContain("Enter your name (1-100 characters).");
    expect(messages({ ...ok, name: "x".repeat(201) })).toContain("Enter your name (1-100 characters).");
    expect(messages({ ...ok, name: "  Layla   Hassan  " })).toEqual([]);
  });

  it("GF0A-06 sign-in only requires both fields (the server decides about credentials)", () => {
    expect(signInSchema.safeParse({ email: "", password: "" }).success).toBe(false);
    expect(signInSchema.safeParse({ email: "anything", password: "x" }).success).toBe(true);
  });
});
