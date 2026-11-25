import { RailShell } from "@/features/shell/components/AppShell";

/** Rail shell (UI §6.3): Course Workspace. */
export default function RailLayout({ children }: { children: React.ReactNode }) {
  return <RailShell>{children}</RailShell>;
}
