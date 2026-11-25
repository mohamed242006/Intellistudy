"use client";

import { useRef, useState } from "react";
import { Button } from "@/design-system/components/Button";
import { Modal } from "@/design-system/components/Modal";
import { FormAlert } from "@/features/auth/components/FormAlert";
import { ApiError } from "@/lib/api/errors";
import { plural } from "@/lib/format/format";
import { useDeleteCourse } from "../hooks";
import { COURSE_ERRORS, FIGMA, PROVISIONAL } from "../strings";

/** Destructive Modal (UI §7.14, D-9; gate GF0B-13). Starts on Cancel; only "Delete course" deletes. */
export function DeleteCourseModal({ open, courseId, fileCount, onClose, onDeleted }: {
  open: boolean;
  courseId: string;
  /** Exact count when every page of documents is loaded, otherwise null. */
  fileCount: number | null;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const cancel = useRef<HTMLButtonElement>(null);
  const mutation = useDeleteCourse(courseId);
  const [error, setError] = useState<string | null>(null);
  const files = fileCount === null ? PROVISIONAL.allFiles : plural(fileCount, "file");
  return (
    <Modal
      open={open}
      onClose={() => {
        setError(null);
        onClose();
      }}
      busy={mutation.isPending}
      initialFocus={cancel}
      title={FIGMA.deleteCourseTitle}
      description={PROVISIONAL.deleteCourseBody(files)}
      footer={
        <>
          <Button ref={cancel} variant="secondary" onClick={onClose} disabled={mutation.isPending}>
            {FIGMA.cancel}
          </Button>
          <Button
            variant="danger"
            loading={mutation.isPending}
            onClick={() => {
              setError(null);
              mutation.mutate(undefined, {
                onSuccess: onDeleted,
                onError: (e) => setError(e instanceof ApiError && e.kind === "network" ? COURSE_ERRORS.offline : COURSE_ERRORS.deleteFailed),
              });
            }}
          >
            {FIGMA.deleteCourse}
          </Button>
        </>
      }
    >
      <FormAlert message={error} />
    </Modal>
  );
}
