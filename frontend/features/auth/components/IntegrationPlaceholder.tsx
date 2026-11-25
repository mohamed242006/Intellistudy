"use client";

import { Button } from "@/design-system/components/Button";
import { useAuth } from "@/lib/auth/auth-provider";

/**
 * F0-A INTEGRATION PLACEHOLDER (gate GF0A-19). Proves the session and route protection end to end. It is not the
 * Dashboard and shows no Dashboard design or sample data; F0-B replaces this route with the Dashboard frame.
 */
export function IntegrationPlaceholder() {
  const { user, signOut } = useAuth();
  return (
    <main className="mx-auto flex min-h-screen max-w-auth-card flex-col justify-center gap-6 p-10">
      <p className="text-caption-strong text-fg-secondary">F0-A INTEGRATION PLACEHOLDER</p>
      <h1 className="text-h2 text-fg">F0-A integration placeholder</h1>
      <p className="text-body text-fg-secondary">
        This page only proves that sign-in, session restore and route protection work. It is not the Dashboard.
      </p>
      {user ? (
        <dl className="flex flex-col gap-1 text-body-sm">
          <dt className="text-fg-secondary">Signed in as</dt>
          <dd data-testid="signed-in-user" className="text-fg">
            {user.name} ({user.email})
          </dd>
        </dl>
      ) : null}
      <div>
        <Button variant="secondary" onClick={() => void signOut()}>
          Sign out
        </Button>
      </div>
    </main>
  );
}
