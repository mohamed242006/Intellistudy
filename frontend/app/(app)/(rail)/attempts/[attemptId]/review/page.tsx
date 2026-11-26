"use client";

import { useParams } from "next/navigation";
import { ReviewPage } from "@/features/quiz/components/ReviewPage";

export default function AttemptReviewPage() {
  const { attemptId } = useParams<{ attemptId: string }>();
  return <ReviewPage key={attemptId} attemptId={attemptId} />;
}
