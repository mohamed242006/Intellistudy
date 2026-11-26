"use client";

import { useParams } from "next/navigation";
import { Suspense } from "react";
import { QuizListPage } from "@/features/quiz/components/QuizListPage";

export default function CourseQuizzesPage() {
  const { courseId } = useParams<{ courseId: string }>();
  return (
    <Suspense>
      <QuizListPage key={courseId} courseId={courseId} />
    </Suspense>
  );
}
