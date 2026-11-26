"use client";

import { useParams } from "next/navigation";
import { Suspense } from "react";
import { CourseSummaryPage } from "@/features/summary/components/CourseSummaryPage";

/** One combined summary (several source files). */
export default function CombinedSummaryPage() {
  const { summaryId } = useParams<{ summaryId: string }>();
  return (
    <Suspense>
      <CourseSummaryPage key={summaryId} summaryId={summaryId} />
    </Suspense>
  );
}
