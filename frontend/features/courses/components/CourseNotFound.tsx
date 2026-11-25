import { ButtonLink } from "@/design-system/components/Button";
import { EmptyState } from "@/design-system/components/EmptyState";
import { PROVISIONAL } from "../strings";

/**
 * The single not-found state for a course (gate GF0B-11). Missing, foreign and malformed ids all reach it with the
 * same backend 404, and it shows nothing about the requested course.
 */
export function CourseNotFound() {
  return (
    <div className="px-4 py-10 lg:px-12">
      <EmptyState
        size="page"
        icon="search"
        headingLevel={1}
        title={PROVISIONAL.notFoundTitle}
        body={PROVISIONAL.notFoundBody}
        action={<ButtonLink href="/">{PROVISIONAL.backToDashboard}</ButtonLink>}
      />
    </div>
  );
}
