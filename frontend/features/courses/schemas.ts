import { z } from "zod";

/**
 * Course name, mirroring `CourseName` in backend/app/api/v1/schemas.py: whitespace stripped, then 1-200 characters
 * (Python counts code points, so this does too). Duplicate names are allowed by the backend, so no uniqueness rule.
 */
export const COURSE_NAME_MAX = 200;

export const courseNameSchema = z
  .string()
  .transform((value) => value.trim())
  .refine((value) => value.length > 0, { message: "required" })
  .refine((value) => Array.from(value).length <= COURSE_NAME_MAX, { message: "too_long" });

export const courseFormSchema = z.object({ name: courseNameSchema });
export type CourseFormInput = z.input<typeof courseFormSchema>;
export type CourseFormOutput = z.output<typeof courseFormSchema>;
