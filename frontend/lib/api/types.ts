/** Response and request shapes, taken from the generated backend schema (lib/api/schema.d.ts). Never hand-written. */
import type { components } from "./schema";

export type UserOut = components["schemas"]["UserOut"];
export type TokenResponse = components["schemas"]["TokenResponse"];
export type LoginRequest = components["schemas"]["LoginRequest"];
export type RegisterRequest = components["schemas"]["RegisterRequest"];

export type CourseOut = components["schemas"]["CourseOut"];
export type CourseList = components["schemas"]["CourseList"];
export type CourseCreate = components["schemas"]["CourseCreate"];
export type CourseUpdate = components["schemas"]["CourseUpdate"];
export type DocumentOut = components["schemas"]["DocumentOut"];
export type DocumentList = components["schemas"]["DocumentList"];
export type UploadResponse = components["schemas"]["UploadResponse"];
export type UploadedDocument = components["schemas"]["UploadedDocument"];
