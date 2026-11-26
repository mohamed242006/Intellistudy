"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/design-system/components/Button";
import { CardSkeleton } from "@/design-system/components/Card";
import { EmptyState } from "@/design-system/components/EmptyState";
import { Notice } from "@/design-system/components/Notice";
import { CourseCard } from "@/features/courses/components/CourseCard";
import { CourseFormModal } from "@/features/courses/components/CourseFormModal";
import { CoursePickerModal } from "@/features/courses/components/CoursePickerModal";
import { useCourses } from "@/features/courses/hooks";
import { FIGMA, PROVISIONAL } from "@/features/courses/strings";
import { useAuth } from "@/lib/auth/auth-provider";
import { firstName, greeting, greetingDate } from "@/lib/format/format";
import { useNow } from "@/lib/format/use-now";

/**
 * Dashboard (UI §8.2; gates GF0B-04..09). Only backend data: the greeting header from /auth/me and "Your courses" from
 * GET /courses. Rows A and C (recommendation, streak, weakest topics, recent activity) have no backend data and are
 * not rendered (plan 11.1, decision 11.3-1).
 */
export function Dashboard() {
  const { user } = useAuth();
  const router = useRouter();
  const now = useNow();
  const courses = useCourses();
  const list = courses.data?.pages.flatMap((page) => page.items) ?? [];
  const [creating, setCreating] = useState<null | "open" | "then-upload">(null);
  const [choosing, setChoosing] = useState(false);
  const section = useRef<HTMLElement>(null);

  // `/#courses` (Sidebar "Courses", `/courses`): bring "Your courses" into view and focus it.
  useEffect(() => {
    const focusCourses = () => {
      if (window.location.hash === "#courses") {
        section.current?.scrollIntoView({ block: "start" });
        section.current?.focus({ preventScroll: true });
      }
    };
    focusCourses();
    window.addEventListener("hashchange", focusCourses);
    return () => window.removeEventListener("hashchange", focusCourses);
  }, [courses.isSuccess]);

  const uploadFiles = () => {
    if (!courses.isSuccess) return;
    if (list.length === 0) setCreating("then-upload");
    else if (list.length === 1 && !courses.hasNextPage) router.push(`/courses/${encodeURIComponent(list[0]!.id)}/upload`);
    else setChoosing(true);
  };

  return (
    <div className="flex flex-col gap-8 px-4 py-6 md:px-8 lg:px-12 lg:pt-10 lg:pb-12">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-2">
          <h1 className="text-h1 break-words text-fg">
            {greeting(now)}
            {user ? `, ${firstName(user.name)}` : ""}
          </h1>
          <p className="text-body text-fg-secondary">{greetingDate(now)}</p>
        </div>
        <Button onClick={uploadFiles} loading={courses.isPending}>
          {FIGMA.uploadFiles}
        </Button>
      </header>

      <section ref={section} id="courses" tabIndex={-1} aria-labelledby="your-courses" className="flex scroll-mt-6 flex-col gap-4 outline-none">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h2 id="your-courses" className="text-h2 text-fg">
            {FIGMA.yourCourses}
          </h2>
          <Button variant="ghost" onClick={() => setCreating("open")}>
            {FIGMA.newCourse}
          </Button>
        </div>

        {courses.isPending ? (
          <div aria-busy="true" aria-label={PROVISIONAL.loadingCourses} role="status" className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,300px),1fr))] gap-6">
            <CardSkeleton />
            <CardSkeleton />
            <CardSkeleton />
          </div>
        ) : courses.isError && list.length === 0 ? (
          <div role="alert" className="flex flex-col items-start gap-4">
            <Notice tone="warning" title={PROVISIONAL.loadError} body={PROVISIONAL.loadErrorBody} />
            <Button variant="secondary" onClick={() => void courses.refetch()}>
              {PROVISIONAL.tryAgain}
            </Button>
          </div>
        ) : list.length === 0 ? (
          <div className="rounded-xl border border-line bg-surface">
            <EmptyState
              size="page"
              icon="book"
              headingLevel={3}
              title={PROVISIONAL.emptyTitle}
              body={PROVISIONAL.emptyBody}
              action={<Button onClick={() => setCreating("open")}>{FIGMA.newCourse}</Button>}
            />
          </div>
        ) : (
          <>
            <ul className="motion-stagger grid grid-cols-[repeat(auto-fill,minmax(min(100%,300px),1fr))] gap-6">
              {list.map((course) => (
                <li key={course.id} className="flex min-w-0 flex-col [&>a]:flex-1">
                  <CourseCard course={course} />
                </li>
              ))}
            </ul>
            {courses.hasNextPage ? (
              <div>
                <Button variant="secondary" loading={courses.isFetchingNextPage} onClick={() => void courses.fetchNextPage()}>
                  {PROVISIONAL.showMore}
                </Button>
              </div>
            ) : null}
          </>
        )}
      </section>

      <CourseFormModal
        mode="create"
        open={creating !== null}
        onClose={() => setCreating(null)}
        onSaved={(course) => {
          const next = creating === "then-upload" ? `/courses/${encodeURIComponent(course.id)}/upload` : `/courses/${encodeURIComponent(course.id)}`;
          setCreating(null);
          router.push(next);
        }}
      />
      <CoursePickerModal
        open={choosing}
        courses={list}
        onClose={() => setChoosing(false)}
        onChoose={(courseId) => {
          setChoosing(false);
          router.push(`/courses/${encodeURIComponent(courseId)}/upload`);
        }}
      />
    </div>
  );
}
