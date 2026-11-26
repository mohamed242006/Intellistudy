"use client";

import { useParams } from "next/navigation";
import { Suspense } from "react";
import { CreateSummaryPage } from "@/features/summary/components/CreateSummaryPage";

/** Create a summary from one, several or all ready files of the course (?document=<id> preselects one). */
export default function CourseSummariesPage() {
  const { courseId } = useParams<{ courseId: string }>();
  return (
    <Suspense>
      <CreateSummaryPage key={courseId} courseId={courseId} />
    </Suspense>
  );
}
