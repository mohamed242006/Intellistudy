import type { Metadata } from "next";
import { SettingsPage } from "@/features/account/components/SettingsPage";

export const metadata: Metadata = { title: "Settings" };

/** Account settings: profile (read-only), password change and sign out of all devices (backend auth endpoints). */
export default function Settings() {
  return <SettingsPage />;
}
