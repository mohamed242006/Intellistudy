import { SidebarShell } from "@/features/shell/components/AppShell";

/** Sidebar shell (UI §6.2): Dashboard and Upload. */
export default function SidebarLayout({ children }: { children: React.ReactNode }) {
  return <SidebarShell>{children}</SidebarShell>;
}
