import type { Metadata } from "next";
import { Dashboard } from "@/features/dashboard/components/Dashboard";

export const metadata: Metadata = { title: "Dashboard" };

/** The protected landing route (replaces the F0-A integration placeholder, docs/F0B_GATE.md section 6). */
export default function DashboardPage() {
  return <Dashboard />;
}
