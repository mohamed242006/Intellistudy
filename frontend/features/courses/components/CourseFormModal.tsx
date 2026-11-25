"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Button } from "@/design-system/components/Button";
import { Input } from "@/design-system/components/Input";
import { Modal } from "@/design-system/components/Modal";
import { FormAlert } from "@/features/auth/components/FormAlert";
import { ApiError } from "@/lib/api/errors";
import type { CourseOut } from "@/lib/api/types";
import { useCreateCourse, useRenameCourse } from "../hooks";
import { courseFormError } from "../messages";
import { courseFormSchema, type CourseFormInput, type CourseFormOutput } from "../schemas";
import { FIGMA, PROVISIONAL } from "../strings";

const FIELD_MESSAGE: Record<string, string> = { required: PROVISIONAL.courseNameRequired, too_long: PROVISIONAL.courseNameTooLong };

/** Backend 422 on `name`: string_too_short / string_too_long (Pydantic types; nothing else is read). */
function serverFieldMessage(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.kind !== "validation" || error.code !== "validation_error") return null;
  return PROVISIONAL.courseNameRequired;
}

type CourseFormProps = {
  open: boolean;
  onClose: () => void;
  onSaved: (course: CourseOut) => void;
} & ({ mode: "create" } | { mode: "rename"; course: CourseOut });

/**
 * New course / Rename course (gate GF0B-07, GF0B-12; plan decision 11.3-2): one field, "Course name". The backend's
 * answer is authoritative; the client check only mirrors it. The typed text is kept after a failure.
 * The form mounts when the dialog opens, so each opening starts from fresh values without a reset effect (a reset
 * after opening could erase the first keystrokes).
 */
export function CourseFormModal(props: CourseFormProps) {
  return props.open ? <CourseFormDialog {...props} /> : null;
}

function CourseFormDialog(props: CourseFormProps) {
  const { open, onClose, onSaved, mode } = props;
  const create = useCreateCourse();
  const rename = useRenameCourse(mode === "rename" ? props.course.id : "");
  const mutation = mode === "create" ? create : rename;
  const [formError, setFormError] = useState<string | null>(null);
  const initialName = mode === "rename" ? props.course.name : "";
  const { register, handleSubmit, setError, formState } = useForm<CourseFormInput, unknown, CourseFormOutput>({
    resolver: zodResolver(courseFormSchema),
    defaultValues: { name: initialName },
    mode: "onSubmit",
  });

  const submit = handleSubmit(async ({ name }) => {
    if (mutation.isPending) return;
    setFormError(null);
    try {
      const course = await mutation.mutateAsync(name);
      onSaved(course);
    } catch (error) {
      const field = serverFieldMessage(error);
      if (field) setError("name", { message: field });
      else setFormError(courseFormError(error));
    }
  });

  const fieldError = formState.errors.name?.message;
  return (
    <Modal
      open={open}
      onClose={onClose}
      busy={mutation.isPending}
      title={mode === "create" ? PROVISIONAL.createCourseTitle : PROVISIONAL.renameCourseTitle}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={mutation.isPending}>
            {FIGMA.cancel}
          </Button>
          <Button type="submit" form="course-form" loading={mutation.isPending}>
            {mode === "create" ? PROVISIONAL.createCourse : FIGMA.saveChanges}
          </Button>
        </>
      }
    >
      <form id="course-form" noValidate onSubmit={(event) => void submit(event)} className="flex flex-col gap-4">
        <FormAlert message={formError} />
        <Input
          label={PROVISIONAL.courseNameLabel}
          helper={PROVISIONAL.courseNameHelper}
          autoComplete="off"
          error={fieldError ? (FIELD_MESSAGE[fieldError] ?? fieldError) : undefined}
          {...register("name")}
        />
      </form>
    </Modal>
  );
}
