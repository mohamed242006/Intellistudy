"use client";

import { useId, useState } from "react";
import { Button } from "@/design-system/components/Button";
import { Modal } from "@/design-system/components/Modal";
import type { CourseOut } from "@/lib/api/types";
import { FIGMA, PROVISIONAL } from "../strings";

type PickerProps = {
  open: boolean;
  courses: readonly CourseOut[];
  onClose: () => void;
  onChoose: (courseId: string) => void;
};

/**
 * "Upload files" with several courses (gate GF0B-08; plan decision 11.3-3): choose the course, as a radio group.
 * Mounted on open, so the first course is preselected without an effect that could undo a fast choice.
 */
export function CoursePickerModal(props: PickerProps) {
  return props.open ? <CoursePickerDialog {...props} /> : null;
}

function CoursePickerDialog({ open, courses, onClose, onChoose }: PickerProps) {
  const name = useId();
  const [chosen, setChosen] = useState<string | null>(courses[0]?.id ?? null);
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={PROVISIONAL.chooseCourseTitle}
      description={PROVISIONAL.chooseCourseBody}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {FIGMA.cancel}
          </Button>
          <Button disabled={!chosen} onClick={() => chosen && onChoose(chosen)}>
            {PROVISIONAL.continue}
          </Button>
        </>
      }
    >
      <fieldset className="flex max-h-72 flex-col gap-1 overflow-y-auto">
        <legend className="sr-only">{PROVISIONAL.chooseCourseTitle}</legend>
        {courses.map((course) => (
          <label key={course.id} className="flex min-h-11 cursor-pointer items-center gap-3 rounded-md px-3 hover:bg-subtle">
            <input
              type="radio"
              name={name}
              value={course.id}
              checked={chosen === course.id}
              onChange={() => setChosen(course.id)}
              className="size-4 accent-[var(--color-accent)]"
            />
            <span className="min-w-0 text-body wrap-anywhere text-fg">{course.name}</span>
          </label>
        ))}
      </fieldset>
    </Modal>
  );
}
