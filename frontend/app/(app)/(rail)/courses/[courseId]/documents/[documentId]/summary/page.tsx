"use client";

import { useParams } from "next/navigation";
import { Suspense } from "react";
import { SummaryPage } from "@/features/summary/components/SummaryPage";

export default function DocumentSummaryPage() {
  const { courseId, documentId } = useParams<{ courseId: string; documentId: string }>();
  return (
    <Suspense>
      <SummaryPage key={`${courseId}/${documentId}`} courseId={courseId} documentId={documentId} />
    </Suspense>
  );
}
