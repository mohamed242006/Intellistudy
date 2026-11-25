import { Suspense } from "react";
import { AuthShell } from "@/features/auth/components/AuthShell";
import { RedirectIfAuthenticated } from "@/lib/auth/guards";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <Suspense>
      <RedirectIfAuthenticated>
        <AuthShell>{children}</AuthShell>
      </RedirectIfAuthenticated>
    </Suspense>
  );
}
