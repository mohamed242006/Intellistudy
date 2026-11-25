"use client";

import { useParams } from "next/navigation";
import { Suspense } from "react";
import { Workspace } from "@/features/workspace/components/Workspace";

export default function CourseWorkspacePage() {
  const { courseId } = useParams<{ courseId: string }>();
  return (
    <Suspense>
      <Workspace key={courseId} courseId={courseId} />
    </Suspense>
  );
}
