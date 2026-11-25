/** Backend-shaped fixtures (backend/app/api/v1/schemas.py CourseOut, documents.py DocumentOut). Ids are canonical UUIDs. */
import type { CourseOut, DocumentOut } from "@/lib/api/types";

export const COURSE_ID = "11111111-1111-4111-8111-111111111111";
export const OTHER_ID = "22222222-2222-4222-8222-222222222222";

export function course(overrides: Partial<CourseOut> = {}): CourseOut {
  return {
    id: COURSE_ID,
    name: "Queueing Theory",
    code: null,
    description: null,
    archived: false,
    created_at: "2026-11-25T10:00:00Z",
    updated_at: "2026-11-25T10:00:00Z",
    ...overrides,
  };
}

let n = 0;
export function doc(overrides: Partial<DocumentOut> = {}): DocumentOut {
  n += 1;
  return {
    id: `33333333-3333-4333-8333-${String(n).padStart(12, "0")}`,
    course_id: COURSE_ID,
    file_name: `lecture-${n}.pdf`,
    file_type: "pdf",
    size_bytes: 3_100_000,
    status: "ready",
    progress: 100,
    error_code: null,
    error_message: null,
    page_count: 48,
    chunk_count: 120,
    created_at: "2026-11-25T10:00:00Z",
    updated_at: "2026-11-25T10:00:00Z",
    ready_at: "2026-11-25T10:01:00Z",
    ...overrides,
  };
}

export const page = <T>(items: T[], limit = 50, offset = 0) => ({ items, limit, offset });

export const HOSTILE = ["<script>alert(1)</script>", "<img src=x onerror=alert(1)>", "javascript:alert(1)"] as const;
