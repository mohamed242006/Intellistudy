import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ProtectedLayout from "@/app/(app)/layout";
import LandingPage from "@/app/(app)/page";
import AuthLayout from "@/app/(auth)/layout";
import SignInPage from "@/app/(auth)/signin/page";
import SignUpPage from "@/app/(auth)/signup/page";
import { tokenStore } from "@/lib/auth/token-store";
import { fakeBackend, json, problem, TOKEN, USER } from "../helpers/fake-backend";
import { nav } from "../helpers/navigation";
import { renderWithProviders } from "../helpers/render";

vi.mock("next/navigation", async () => (await import("../helpers/navigation")).navigationMock());
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const signIn = () => (
  <AuthLayout>
    <SignInPage />
  </AuthLayout>
);
const signUp = () => (
  <AuthLayout>
    <SignUpPage />
  </AuthLayout>
);
const protectedPlaceholder = () => (
  <ProtectedLayout>
    <LandingPage />
  </ProtectedLayout>
);

beforeEach(() => {
  tokenStore.clear();
  nav.reset();
});

async function fillSignIn(email: string, password: string) {
  await userEvent.type(await screen.findByLabelText("University email"), email);
  await userEvent.type(screen.getByLabelText("Password"), password);
  await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("GF0A-17 startup", () => {
  it("GF0A-17 makes exactly one refresh at startup (StrictMode) and restores the session", async () => {
    nav.reset("/");
    const backend = fakeBackend().on("POST /auth/refresh", () => json(200, TOKEN())).on("GET /auth/me", () => json(200, USER));
    renderWithProviders(protectedPlaceholder());
    expect(await screen.findByTestId("signed-in-user")).toHaveTextContent("Test Student (student@example.org)");
    expect(backend.count("POST /auth/refresh")).toBe(1);
  });

  it("GF0A-17 a failed startup refresh leaves the visitor signed out on the sign-in page", async () => {
    const backend = fakeBackend().on("POST /auth/refresh", () => problem(401, "session_invalid"));
    renderWithProviders(signIn());
    expect(await screen.findByRole("heading", { level: 1, name: "Welcome back" })).toBeVisible();
    expect(backend.count("POST /auth/refresh")).toBe(1);
    expect(backend.count("GET /auth/me")).toBe(0);
  });
});

describe("GF0A-18 route protection", () => {
  it("GF0A-18 sends an anonymous visitor to /signin with a same-origin return path", async () => {
    nav.reset("/");
    fakeBackend().on("POST /auth/refresh", () => problem(401, "session_invalid"));
    renderWithProviders(protectedPlaceholder());
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/signin?next=%2F"));
    expect(screen.queryByTestId("signed-in-user")).toBeNull();
  });

  it("GF0A-18 sends a signed-in visitor of an auth page to a safe return path, never another origin", async () => {
    nav.reset("/signin", "next=//evil.example/x");
    fakeBackend().on("POST /auth/refresh", () => json(200, TOKEN())).on("GET /auth/me", () => json(200, USER));
    renderWithProviders(signIn());
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/"));
  });
});

describe("GF0A-19 protected placeholder", () => {
  it("GF0A-19 is labelled as an F0-A integration placeholder, not the Dashboard", async () => {
    nav.reset("/");
    fakeBackend().on("POST /auth/refresh", () => json(200, TOKEN())).on("GET /auth/me", () => json(200, USER));
    renderWithProviders(protectedPlaceholder());
    expect(await screen.findByRole("heading", { level: 1, name: "F0-A integration placeholder" })).toBeVisible();
    expect(screen.getByText(/It is not the Dashboard/)).toBeVisible();
    expect(screen.queryByText(/mastery|streak|Good afternoon/i)).toBeNull();
  });
});

describe("GF0A-14 sign in", () => {
  it("GF0A-14 stores the token in memory, loads /auth/me and goes to the return path", async () => {
    nav.reset("/signin", "next=%2F");
    const backend = fakeBackend()
      .on("POST /auth/refresh", () => problem(401, "session_invalid"))
      .on("POST /auth/login", () => json(200, TOKEN(3)))
      .on("GET /auth/me", () => json(200, USER));
    renderWithProviders(signIn());
    await fillSignIn("student@example.org", "lectures4ever");
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/"));
    const login = backend.calls.find((c) => c.path === "/auth/login")!;
    expect(login.body).toEqual({ email: "student@example.org", password: "lectures4ever" });
    expect(login.credentials).toBe("same-origin");
    expect(tokenStore.get()).toBe("access-token-3");
    expect(window.localStorage.length + window.sessionStorage.length).toBe(0);
  });
});

describe("GF0A-15 sign in with bad credentials", () => {
  it("GF0A-15 shows one generic message for an unknown email and for a wrong password", async () => {
    const shown: string[] = [];
    for (const email of ["nobody@example.org", "student@example.org"]) {
      tokenStore.clear();
      fakeBackend()
        .on("POST /auth/refresh", () => problem(401, "session_invalid"))
        .on("POST /auth/login", () => problem(401, "invalid_credentials", "Invalid email or password."));
      const view = renderWithProviders(signIn());
      await fillSignIn(email, "wrong-password-1");
      shown.push((await screen.findByRole("alert")).textContent ?? "");
      view.unmount();
    }
    expect(shown).toEqual(["Invalid email or password.", "Invalid email or password."]);
    expect(nav.replace).not.toHaveBeenCalled();
  });
});

describe("GF0A-16 sign up", () => {
  it("GF0A-16 validates on the client before calling the backend", async () => {
    const backend = fakeBackend().on("POST /auth/refresh", () => problem(401, "session_invalid"));
    renderWithProviders(signUp());
    await userEvent.type(await screen.findByLabelText("Full name"), "Test Student");
    await userEvent.type(screen.getByLabelText("University email"), "not-an-email");
    await userEvent.type(screen.getByLabelText("Password"), "short1");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByText("Enter a valid email address.")).toBeVisible();
    expect(screen.getByText("Password must be at least 10 characters.")).toBeVisible();
    expect(screen.getByLabelText("Password")).toHaveAttribute("aria-invalid", "true");
    expect(backend.count("POST /auth/register")).toBe(0);
    expect(screen.getByLabelText("Password")).toHaveAttribute("placeholder", "At least 10 characters");
    expect(screen.queryByText(/12 characters|\.edu/)).toBeNull();
  });

  it("GF0A-16 registers with exactly the backend fields, then signs in and lands", async () => {
    nav.reset("/signup");
    const backend = fakeBackend()
      .on("POST /auth/refresh", () => problem(401, "session_invalid"))
      .on("POST /auth/register", () => json(201, USER))
      .on("POST /auth/login", () => json(200, TOKEN(4)))
      .on("GET /auth/me", () => json(200, USER));
    renderWithProviders(signUp());
    await userEvent.type(await screen.findByLabelText("Full name"), "Test Student");
    await userEvent.type(screen.getByLabelText("University email"), "student@example.org");
    await userEvent.type(screen.getByLabelText("Password"), "lectures4ever");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/"));
    expect(backend.calls.find((c) => c.path === "/auth/register")!.body).toEqual({
      email: "student@example.org",
      name: "Test Student",
      password: "lectures4ever",
    });
    expect(backend.count("POST /auth/login")).toBe(1);
    expect(window.localStorage.length + window.sessionStorage.length).toBe(0);
  });

  it("GF0A-16 shows server field errors and the generic registration rejection", async () => {
    fakeBackend()
      .on("POST /auth/refresh", () => problem(401, "session_invalid"))
      .on("POST /auth/register", () => problem(422, "weak_password", "This password is too common."), () => problem(409, "registration_rejected", "Registration could not be completed with these details."));
    renderWithProviders(signUp());
    await userEvent.type(await screen.findByLabelText("Full name"), "Test Student");
    await userEvent.type(screen.getByLabelText("University email"), "student@example.org");
    await userEvent.type(screen.getByLabelText("Password"), "password123");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByText("This password is too common.")).toBeVisible();
    await userEvent.clear(screen.getByLabelText("Password"));
    await userEvent.type(screen.getByLabelText("Password"), "another-pass-42");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Registration could not be completed with these details.");
  });
});

describe("GF0A-20 rate limiting", () => {
  it("GF0A-20 shows the wait time from Retry-After, nothing else from the response", async () => {
    fakeBackend()
      .on("POST /auth/refresh", () => problem(401, "session_invalid"))
      .on("POST /auth/login", () => problem(429, "rate_limited", "Too many requests. Try again later.", { "retry-after": "30" }));
    renderWithProviders(signIn());
    await fillSignIn("student@example.org", "lectures4ever");
    expect(await screen.findByRole("alert")).toHaveTextContent("Too many attempts. Try again in 30 seconds.");
  });
});

describe("GF0A-12 logout", () => {
  it("GF0A-12 calls /auth/logout with the CSRF header, clears the token and the query cache, and signs out", async () => {
    nav.reset("/");
    const backend = fakeBackend()
      .on("POST /auth/refresh", () => json(200, TOKEN()))
      .on("GET /auth/me", () => json(200, USER))
      .on("POST /auth/logout", () => new Response(null, { status: 204 }));
    const { queryClient } = renderWithProviders(protectedPlaceholder());
    queryClient.setQueryData(["courses"], [{ id: "c-1" }]);
    await userEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/signin?next=%2F"));
    const logout = backend.calls.find((c) => c.path === "/auth/logout")!;
    expect(logout.headers["X-Requested-With"]).toBe("IntelliStudy");
    expect(logout.headers.Authorization).toBeUndefined();
    expect(logout.credentials).toBe("same-origin");
    expect(tokenStore.get()).toBeNull();
    expect(queryClient.getQueryData(["courses"])).toBeUndefined();
  });
});
