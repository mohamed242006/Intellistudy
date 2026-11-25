import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { nextOffset } from "@/features/courses/hooks";
import { courseNameSchema } from "@/features/courses/schemas";
import { MAX_POLL_FAILURES, POLL_INTERVAL_MS, consecutiveFailures, newFailureTracker, pollDelay } from "@/features/documents/polling";
import { documentActionError } from "@/features/documents/messages";
import { EMPTY_CODES, IN_PROGRESS_STATUSES, TERMINAL_STATUSES, UNSUPPORTED_CODES, documentView, summarise } from "@/features/documents/status";
import { BACKEND_REASONS } from "@/features/documents/strings";
import { initialQueue, nextPending, problemForError, queueReducer } from "@/features/upload/queue";
import { MAX_UPLOAD_BYTES, clientProblem, selectionKey } from "@/features/upload/validation";
import { attachmentFileName, query } from "@/lib/api/client";
import { ApiError, apiErrorFromBody } from "@/lib/api/errors";
import { formatBytes, greeting, greetingDate, initials, plural, relativeTime } from "@/lib/format/format";
import { queryKeys } from "@/lib/query/keys";
import { doc } from "../helpers/data";

const BACKEND = join(process.cwd(), "..", "backend", "app");
const read = (path: string) => readFileSync(join(BACKEND, path), "utf8");
const NOW = new Date("2026-11-25T12:00:00Z");
const file = (name: string, size: number, lastModified = 1) => new File([new Uint8Array(Math.min(size, 8))], name, { lastModified }) as File & { size: number };
const sized = (name: string, size: number, lastModified = 1) => Object.defineProperty(file(name, size, lastModified), "size", { value: size });

describe("GF0B-18 status mapping", () => {
  it("GF0B-18 the frontend knows exactly the backend's DocumentStatus values and REASONS codes and sentences", () => {
    const models = read("db/models.py");
    const enumBlock = models.slice(models.indexOf("class DocumentStatus"), models.indexOf("class", models.indexOf("class DocumentStatus") + 10));
    const statuses = [...enumBlock.matchAll(/= "([a-z_]+)"/g)].map((m) => m[1]);
    expect(statuses.sort()).toEqual([...IN_PROGRESS_STATUSES, ...TERMINAL_STATUSES, "deleting"].sort());

    const source = read("services/documents.py");
    const block = source.slice(source.indexOf("REASONS = {"), source.indexOf("}", source.indexOf("REASONS = {")));
    const reasons = Object.fromEntries([...block.matchAll(/"([a-z_]+)": "((?:[^"\\]|\\.)*)"/g)].map((m) => [m[1], m[2]]));
    expect(reasons).toEqual(BACKEND_REASONS);
  });

  it("GF0B-18 maps in-progress statuses to Extracting, ready to Indexed and failures to Empty / Not supported / Failed", () => {
    for (const status of IN_PROGRESS_STATUSES) expect(documentView(doc({ status }), NOW)).toMatchObject({ status: "extracting", tag: "Extracting", canRetry: false });
    expect(documentView(doc({ status: "ready", page_count: 48, ready_at: "2026-11-25T11:58:00Z" }), NOW)).toEqual({ status: "indexed", tag: "Indexed", detail: "48 pages · indexed 2 minutes ago", canRetry: false });
    expect(documentView(doc({ status: "ready", file_type: "pptx", page_count: 1, ready_at: "2026-11-25T11:59:59Z" }), NOW).detail).toBe("1 slide · indexed just now");
    for (const code of EMPTY_CODES) expect(documentView(doc({ status: "failed", error_code: code }), NOW)).toMatchObject({ status: "empty", tag: "Empty", canRetry: false });
    for (const code of UNSUPPORTED_CODES) expect(documentView(doc({ status: "failed", error_code: code }), NOW)).toMatchObject({ status: "unsupported", tag: "Not supported", canRetry: false });
    expect(documentView(doc({ status: "failed", error_code: "corrupted" }), NOW)).toEqual({ status: "failed", tag: "Failed", detail: "The file appears to be damaged.", canRetry: true });
    expect(documentView(doc({ status: "failed", error_code: "something_new" }), NOW).detail).toBe(BACKEND_REASONS.internal_error);
    expect(documentView(doc({ status: "mystery" }), NOW)).toMatchObject({ status: "failed", canRetry: false });
  });

  it("GF0B-18 no OCR status exists and every status has a text tag", () => {
    const tags = ["queued", "ready", "failed"].map((status) => documentView(doc({ status, error_code: "no_text" }), NOW).tag);
    expect(tags.every((t) => t.length > 0)).toBe(true);
    expect(JSON.stringify(tags)).not.toMatch(/OCR/);
  });

  it("GF0B-10 summarises indexed, processing and attention counts from real documents", () => {
    const docs = [doc(), doc({ status: "embedding" }), doc({ status: "failed", error_code: "no_text" }), doc({ status: "queued" })];
    expect(summarise(docs, true)).toEqual({ total: 4, indexed: 1, processing: 2, attention: 1, complete: true });
  });
});

describe("GF0B-19 polling rules", () => {
  it("GF0B-19 polls every 2 s only while a document is in progress", () => {
    expect(POLL_INTERVAL_MS).toBe(2000);
    expect(pollDelay([doc(), doc({ status: "indexing" })], 0)).toBe(2000);
    expect(pollDelay([doc(), doc({ status: "failed" })], 0)).toBe(false);
    expect(pollDelay([], 0)).toBe(false);
  });

  it("GF0B-19 backs off after failed polls (bounded at 30 s) and stops after MAX_POLL_FAILURES", () => {
    const busy = [doc({ status: "queued" })];
    expect([0, 1, 2, 3, 4].map((f) => pollDelay(busy, f))).toEqual([2000, 4000, 8000, 16000, 30000]);
    expect(pollDelay(busy, MAX_POLL_FAILURES)).toBe(false);
  });

  it("GF0B-19 counts consecutive failed fetches from query state and resets on success", () => {
    const tracker = newFailureTracker();
    expect(consecutiveFailures(tracker, { dataUpdatedAt: 1, errorUpdateCount: 0 })).toBe(0);
    expect(consecutiveFailures(tracker, { dataUpdatedAt: 1, errorUpdateCount: 2 })).toBe(2);
    expect(consecutiveFailures(tracker, { dataUpdatedAt: 5, errorUpdateCount: 2 })).toBe(0);
    expect(consecutiveFailures(tracker, { dataUpdatedAt: 5, errorUpdateCount: 3 })).toBe(1);
  });
});

describe("GF0B-06 pagination", () => {
  it("GF0B-06 asks for another page only while the last page was full (the backend sends no total)", () => {
    expect(nextOffset({ items: new Array(50).fill(0), limit: 50, offset: 0 })).toBe(50);
    expect(nextOffset({ items: new Array(50).fill(0), limit: 50, offset: 50 })).toBe(100);
    expect(nextOffset({ items: new Array(49).fill(0), limit: 50, offset: 50 })).toBeUndefined();
    expect(nextOffset({ items: [], limit: 50, offset: 0 })).toBeUndefined();
    expect(query({ limit: 50, offset: 0 })).toBe("?limit=50&offset=0");
  });
});

describe("GF0B-07 course name rules", () => {
  it("GF0B-07 mirrors the backend: whitespace stripped, then 1-200 characters (code points); duplicates allowed", () => {
    const schemas = read("api/v1/schemas.py");
    expect(schemas).toMatch(/CourseName = Annotated\[str, StringConstraints\(strip_whitespace=True, min_length=1, max_length=200\)\]/);
    expect(courseNameSchema.parse("  Queueing Theory  ")).toBe("Queueing Theory");
    expect(courseNameSchema.safeParse("   ").success).toBe(false);
    expect(courseNameSchema.safeParse("a".repeat(200)).success).toBe(true);
    expect(courseNameSchema.safeParse("a".repeat(201)).success).toBe(false);
    expect(courseNameSchema.safeParse("😀".repeat(200)).success).toBe(true); // 400 UTF-16 units, 200 code points
  });
});

describe("GF0B-14 client-side upload checks", () => {
  it("GF0B-14 the size limit and extensions match backend config and storage", () => {
    expect(read("core/config.py")).toMatch(/max_upload_bytes: int = Field\(default=100 \* 1024 \* 1024/);
    expect(read("services/storage.py")).toContain('ALLOWED_EXTENSIONS = ("pdf", "docx", "pptx")');
    expect(MAX_UPLOAD_BYTES).toBe(100 * 1024 * 1024);
  });

  it("GF0B-14 accepts pdf/docx/pptx (any case), refuses other types, empty files and files over 100 MB", () => {
    expect(clientProblem(sized("a.PDF", 10))).toBeNull();
    expect(clientProblem(sized("a.docx", 10))).toBeNull();
    expect(clientProblem(sized("a.pptx", MAX_UPLOAD_BYTES))).toBeNull();
    expect(clientProblem(sized("a.doc", 10))).toBe("unsupported_type");
    expect(clientProblem(sized("notes", 10))).toBe("unsupported_type");
    expect(clientProblem(sized("a.pdf", 0))).toBe("empty_file");
    expect(clientProblem(sized("a.pdf", MAX_UPLOAD_BYTES + 1))).toBe("file_too_large");
  });

  it("GF0B-14 the same file selected twice while queued is queued once; rejected files get a row", () => {
    const a = sized("a.pdf", 10, 5);
    let ids = 0;
    const makeId = () => `c${++ids}`;
    let state = queueReducer(initialQueue, { type: "add", files: [a, sized("b.txt", 10)], makeId });
    state = queueReducer(state, { type: "add", files: [sized("a.pdf", 10, 5)], makeId });
    expect(state.items.map((i) => [i.file.name, i.phase, i.problem?.status ?? null])).toEqual([
      ["b.txt", "problem", "unsupported"],
      ["a.pdf", "pending", null],
    ]);
    expect(selectionKey(a)).toBe(selectionKey(sized("a.pdf", 10, 5)));
  });
});

describe("GF0B-16 upload queue", () => {
  it("GF0B-16 starts the oldest pending row first and leaves the queue when accepted", () => {
    let ids = 0;
    const makeId = () => `c${++ids}`;
    let state = queueReducer(initialQueue, { type: "add", files: [sized("1.pdf", 1), sized("2.pdf", 1)], makeId });
    state = queueReducer(state, { type: "add", files: [sized("3.pdf", 1)], makeId });
    expect(nextPending(state)?.file.name).toBe("1.pdf");
    state = queueReducer(state, { type: "start", id: nextPending(state)!.id });
    state = queueReducer(state, { type: "progress", id: "c1", percent: 40 });
    expect(state.items.find((i) => i.id === "c1")).toMatchObject({ phase: "uploading", progress: 40 });
    expect(nextPending(state)?.file.name).toBe("2.pdf");
    state = queueReducer(state, { type: "accepted", id: "c1" });
    expect(state.items.map((i) => i.file.name)).toEqual(["3.pdf", "2.pdf"]);
  });

  it("GF0B-16 retry is offered only for retryable problems; remove drops a row", () => {
    let state = queueReducer(initialQueue, { type: "add", files: [sized("1.pdf", 1)], makeId: () => "x" });
    state = queueReducer(state, { type: "problem", id: "x", problem: { status: "failed", message: "m", retryable: false } });
    expect(queueReducer(state, { type: "retry", id: "x" }).items[0]!.phase).toBe("problem");
    state = queueReducer(state, { type: "problem", id: "x", problem: { status: "failed", message: "m", retryable: true } });
    expect(queueReducer(state, { type: "retry", id: "x" }).items[0]!.phase).toBe("pending");
    expect(queueReducer(state, { type: "remove", id: "x" }).items).toEqual([]);
  });
});

describe("GF0B-17 server rejections on the row", () => {
  const err = (status: number, code: string, extra: Record<string, unknown> = {}, retryAfter: string | null = null) =>
    apiErrorFromBody(status, { type: `about:blank#${code}`, detail: "x", ...extra }, retryAfter);

  it("GF0B-17 maps every upload failure code to its row status and sentence", () => {
    expect(problemForError(err(422, "upload_rejected", { files: [{ file: "a.pdf", reason: "type_mismatch", message: "x" }] }))).toEqual({ status: "unsupported", message: "The file's content does not match its extension.", retryable: false });
    expect(problemForError(err(422, "upload_rejected", { files: [{ file: "a.pdf", reason: "empty_file" }] }))).toMatchObject({ status: "empty", retryable: false });
    expect(problemForError(err(413, "file_too_large"))).toEqual({ status: "failed", message: "This file is larger than 100 MB.", retryable: false });
    expect(problemForError(err(413, "quota_exceeded")).message).toBe("Your storage quota is full. Delete documents to upload more.");
    expect(problemForError(err(429, "queue_full"))).toMatchObject({ message: "Too many documents are still processing. Try again later.", retryable: true });
    expect(problemForError(err(429, "rate_limited", {}, "120")).message).toBe("Too many uploads in the last hour. Try again in 2 minutes.");
    expect(problemForError(err(404, "not_found"))).toMatchObject({ message: "This course no longer exists.", retryable: false });
    expect(problemForError(new ApiError({ kind: "network", status: 0 }))).toMatchObject({ retryable: true });
    expect(problemForError(new ApiError({ kind: "session_expired", status: 401 }))).toMatchObject({ retryable: false });
    expect(problemForError(err(500, "internal_error"))).toMatchObject({ message: "Upload failed. Try again later." });
  });

  it("GF0B-17 keeps only well-formed reason codes from an upload_rejected body", () => {
    const e = err(422, "upload_rejected", { files: [{ file: "a.pdf", reason: "<b>x</b>" }, { file: 7, reason: "empty_file" }, "junk"] });
    expect(e.files).toEqual([{ file: "", reason: "empty_file" }]);
  });
});

describe("GF0B-26 error copy", () => {
  it("GF0B-26 document actions map backend codes to fixed sentences and never echo a problem body", () => {
    const hostile = apiErrorFromBody(409, { type: "about:blank#not_failed", detail: "<script>x</script> /srv/data" }, null);
    expect(documentActionError(hostile)).toBe("This file is no longer in a failed state.");
    expect(documentActionError(apiErrorFromBody(429, { type: "about:blank#queue_full" }, null))).toBe("Too many documents are still processing. Try again later.");
    expect(documentActionError(apiErrorFromBody(404, { type: "about:blank#not_found" }, null))).toBe("This file no longer exists.");
    expect(documentActionError(apiErrorFromBody(500, { type: "about:blank", detail: "Traceback (most recent call last)" }, null))).toBe("That didn’t work. Try again.");
    expect(documentActionError(new Error("boom"))).toBe("That didn’t work. Try again.");
    for (const status of [400, 403, 409, 413, 415, 422, 500]) {
      const e = apiErrorFromBody(status, { type: "about:blank#x", detail: "secret path /home/x" }, null);
      expect(e.userMessage).toBeNull();
    }
  });
});

describe("GF0B-23 query keys", () => {
  it("GF0B-23 keys are stable, per resource, and a course's document keys share one prefix", () => {
    expect(queryKeys.courseList()).toEqual(["courses", { limit: 50 }]);
    expect(queryKeys.course("c")).toEqual(["course", "c"]);
    expect(queryKeys.documentList("c")).toEqual(["documents", "c", { limit: 100 }]);
    expect(queryKeys.documentList("c").slice(0, 2)).toEqual(queryKeys.documentsOf("c"));
    expect(queryKeys.document("d")).toEqual(["document", "d"]);
    expect(queryKeys.documentList("a")).not.toEqual(queryKeys.documentList("b"));
  });
});

describe("GF0B-22 download file name", () => {
  it("GF0B-22 reads the RFC 6266 name of an attachment and refuses inline or path-like names", () => {
    expect(attachmentFileName("attachment; filename*=UTF-8''Lecture%201%20%E2%80%94%20Intro.pdf")).toBe("Lecture 1 — Intro.pdf");
    expect(attachmentFileName("attachment; filename*=UTF-8''..%2F..%2Fetc%2Fpasswd")).toBe(".._.._etc_passwd");
    expect(attachmentFileName("inline; filename*=UTF-8''a.pdf")).toBeNull();
    expect(attachmentFileName(null)).toBeNull();
    expect(attachmentFileName("attachment; filename*=UTF-8''%E0%A4%A")).toBeNull();
  });
});

describe("GF0B-10 formats", () => {
  it("GF0B-10 sizes, plurals, dates, greetings and initials follow UI §18 D-18, D-19, D-21", () => {
    expect(formatBytes(3_100_000)).toBe("3.1 MB");
    expect(formatBytes(16_393)).toBe("16 KB");
    expect(formatBytes(543)).toBe("543 B");
    expect(plural(1, "file")).toBe("1 file");
    expect(plural(7, "file")).toBe("7 files");
    expect(greetingDate(new Date(2026, 9, 22, 15))).toBe("Thursday, 22 October");
    expect([9, 13, 20].map((h) => greeting(new Date(2026, 9, 22, h)))).toEqual(["Good morning", "Good afternoon", "Good evening"]);
    expect(initials("Layla Hassan")).toBe("LH");
    expect(initials("Layla Amal Hassan")).toBe("LH");
    expect(initials("layla")).toBe("LA");
    expect(relativeTime("2026-11-24T10:00:00Z", NOW)).toBe("Yesterday");
    expect(relativeTime("2026-11-25T09:00:00Z", NOW)).toBe("3 hours ago");
    expect(relativeTime("not a date", NOW)).toBe("");
  });
});
