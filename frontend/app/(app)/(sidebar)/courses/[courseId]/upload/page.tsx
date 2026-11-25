"use client";

import { useParams } from "next/navigation";
import { UploadPage } from "@/features/upload/components/UploadPage";

export default function CourseUploadPage() {
  const { courseId } = useParams<{ courseId: string }>();
  return <UploadPage key={courseId} courseId={courseId} />;
}
