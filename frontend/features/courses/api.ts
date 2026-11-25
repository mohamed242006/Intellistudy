/** Course endpoints (backend/app/api/v1/courses.py). Ids go in the path only, URL-encoded. */
import { apiRequest, query } from "@/lib/api/client";
import type { CourseList, CourseOut } from "@/lib/api/types";

const path = (courseId: string) => `/courses/${encodeURIComponent(courseId)}`;

export function listCourses(limit: number, offset: number, signal?: AbortSignal): Promise<CourseList> {
  return apiRequest<CourseList>(`/courses${query({ limit, offset })}`, { signal });
}

export function getCourse(courseId: string, signal?: AbortSignal): Promise<CourseOut> {
  return apiRequest<CourseOut>(path(courseId), { signal });
}

/** Only `name` is collected (plan decision 11.3-2); code and description stay unset. */
export function createCourse(name: string): Promise<CourseOut> {
  return apiRequest<CourseOut>("/courses", { method: "POST", body: { name } });
}

export function renameCourse(courseId: string, name: string): Promise<CourseOut> {
  return apiRequest<CourseOut>(path(courseId), { method: "PATCH", body: { name } });
}

export function deleteCourse(courseId: string): Promise<void> {
  return apiRequest<void>(path(courseId), { method: "DELETE" });
}
