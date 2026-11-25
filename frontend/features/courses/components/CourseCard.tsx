"use client";

import { Card, type CardStatusTone } from "@/design-system/components/Card";
import { useDocuments } from "@/features/documents/hooks";
import { summarise } from "@/features/documents/status";
import type { CourseOut } from "@/lib/api/types";
import { plural } from "@/lib/format/format";
import { FIGMA, PROVISIONAL } from "../strings";

/**
 * Dashboard course card (UI §7.9, §8.2; gate GF0B-04): name, the course's own description if it has one, a processing
 * line and the file count, all from the backend. No mastery percentage (no backend data, plan 11.1).
 */
export function CourseCard({ course }: { course: CourseOut }) {
  const documents = useDocuments(course.id, { poll: true });
  let status: { text: string; tone: CardStatusTone } | null = null;
  let meta: string | null = null;
  if (documents.isSuccess) {
    const summary = summarise(documents.documents, documents.complete);
    if (summary.total === 0) status = { text: PROVISIONAL.noFilesYet, tone: "neutral" };
    else if (summary.processing > 0) status = { text: PROVISIONAL.processing(summary.processing), tone: "accent" };
    else if (summary.attention > 0) status = { text: PROVISIONAL.needAttention(summary.attention), tone: "danger" };
    else status = { text: FIGMA.allIndexed, tone: "success" };
    if (summary.total > 0) meta = summary.complete ? plural(summary.total, "file") : PROVISIONAL.moreFiles(summary.total);
  }
  return <Card href={`/courses/${encodeURIComponent(course.id)}`} title={course.name} description={course.description} status={status} meta={meta} />;
}
