"use client";

/** Course server state (gate GF0B-06, -07, -12, -13, -23). */
import { useInfiniteQuery, useMutation, useQuery, useQueryClient, type InfiniteData, type QueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api/errors";
import type { CourseList, CourseOut } from "@/lib/api/types";
import { COURSE_PAGE_SIZE, queryKeys } from "@/lib/query/keys";
import { createCourse, deleteCourse, getCourse, listCourses, renameCourse } from "./api";

/** The next offset, or undefined when the last page was not full (the backend sends no total). */
export function nextOffset(lastPage: { items: unknown[]; limit: number; offset: number }): number | undefined {
  return lastPage.items.length < lastPage.limit ? undefined : lastPage.offset + lastPage.items.length;
}

export function useCourses() {
  return useInfiniteQuery({
    queryKey: queryKeys.courseList(),
    queryFn: ({ pageParam, signal }) => listCourses(COURSE_PAGE_SIZE, pageParam, signal),
    initialPageParam: 0,
    getNextPageParam: nextOffset,
  });
}

export function useCourse(courseId: string, { enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({ queryKey: queryKeys.course(courseId), queryFn: ({ signal }) => getCourse(courseId, signal), enabled });
}

/**
 * Drop a deleted course's cached data (the course and its documents). Called by the page after it stopped observing
 * them, so nothing refetches a course that no longer exists (GF0B-13).
 */
export function forgetCourse(client: QueryClient, courseId: string): void {
  client.removeQueries({ queryKey: queryKeys.course(courseId) });
  client.removeQueries({ queryKey: queryKeys.documentsOf(courseId) });
}

export function useCreateCourse() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => createCourse(name),
    onSuccess: (course) => {
      client.setQueryData(queryKeys.course(course.id), course);
      void client.invalidateQueries({ queryKey: queryKeys.courses() });
    },
  });
}

function replaceInList(data: InfiniteData<CourseList, number> | undefined, course: CourseOut) {
  if (!data) return data;
  return { ...data, pages: data.pages.map((page) => ({ ...page, items: page.items.map((c) => (c.id === course.id ? course : c)) })) };
}

export function useRenameCourse(courseId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => renameCourse(courseId, name),
    onSuccess: (course) => {
      client.setQueryData(queryKeys.course(courseId), course);
      // Show the new name at once, but keep the list stale: patching marks it fresh, and it may predate other changes
      // (for example a course created since it was fetched).
      client.setQueriesData<InfiniteData<CourseList, number>>({ queryKey: queryKeys.courses() }, (data) => replaceInList(data, course));
      void client.invalidateQueries({ queryKey: queryKeys.courses() });
    },
  });
}

/** Delete; a 404 means it is already gone, which is the outcome the user asked for. The caller then forgets the course. */
export function useDeleteCourse(courseId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      try {
        await deleteCourse(courseId);
      } catch (error) {
        if (!(error instanceof ApiError && error.kind === "not_found")) throw error;
      }
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.courses() });
    },
  });
}
