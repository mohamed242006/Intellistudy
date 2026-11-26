"use client";

import { useParams } from "next/navigation";
import { AttemptPage } from "@/features/quiz/components/AttemptPage";

export default function QuizAttemptPage() {
  const { quizId, attemptId } = useParams<{ quizId: string; attemptId: string }>();
  return <AttemptPage key={`${quizId}/${attemptId}`} quizId={quizId} attemptId={attemptId} />;
}
