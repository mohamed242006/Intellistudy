import { RequireAuth } from "@/lib/auth/guards";

/** Every route in this group requires a session (gate GF0A-18). */
export default function ProtectedLayout({ children }: { children: React.ReactNode }) {
  return <RequireAuth>{children}</RequireAuth>;
}
