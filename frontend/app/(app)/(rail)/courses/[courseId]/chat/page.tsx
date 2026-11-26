"use client";

import { useParams } from "next/navigation";
import { Suspense } from "react";
import { ChatPage } from "@/features/chat/components/ChatPage";

export default function CourseChatPage() {
  const { courseId } = useParams<{ courseId: string }>();
  return (
    <Suspense>
      <ChatPage key={courseId} courseId={courseId} />
    </Suspense>
  );
}
