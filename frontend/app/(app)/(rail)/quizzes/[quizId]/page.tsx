"use client";

import { useParams } from "next/navigation";
import { QuizPage } from "@/features/quiz/components/QuizPage";

export default function QuizOverviewPage() {
  const { quizId } = useParams<{ quizId: string }>();
  return <QuizPage key={quizId} quizId={quizId} />;
}
