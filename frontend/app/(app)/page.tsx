import type { Metadata } from "next";
import { IntegrationPlaceholder } from "@/features/auth/components/IntegrationPlaceholder";

export const metadata: Metadata = { title: "F0-A integration placeholder" };

export default function LandingPage() {
  return <IntegrationPlaceholder />;
}
