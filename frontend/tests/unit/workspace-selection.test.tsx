import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { sendMessage } from "@/features/chat/api";
import { clearHandoffs, handOff, takeHandoff } from "@/features/documents/handoff";
import { QuizListPage } from "@/features/quiz/components/QuizListPage";
import { SummaryPage } from "@/features/summary/components/SummaryPage";
import { Workspace } from "@/features/workspace/components/Workspace";
import { tokenStore } from "@/lib/auth/token-store";
import type { DocumentOut } from "@/lib/api/types";
import { renderPage, signedInBackend } from "../helpers/app";
import { COURSE_ID, course, doc, page } from "../helpers/data";
import { json, problem } from "../helpers/fake-backend";
import { nav } from "../helpers/navigation";

vi.mock("next/navigation", async () => (await import("../helpers/navigation")).navigationMock());
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode; scroll?: boolean }) => {
    const attributes: Record<string, unknown> = { ...rest };
    delete attributes.scroll;
    return (
      <a href={href} {...attributes}>
        {children}
      </a>
    );
  },
}));

beforeEach(() => {
  tokenStore.clear();
  clearHandoffs();
});

const SUMMARY_ID = "55555555-5555-4555-8555-555555555555";
const A = doc({ file_name: "Lecture 1 — Arrivals.pdf" });
const B = doc({ file_name: "Lecture 2 — Networks.pptx", file_type: "pptx", page_count: 12 });
const C = doc({ file_name: "Lecture 3 — Queues.docx", file_type: "docx" });
const BUSY = doc({ file_name: "busy.pdf", status: "embedding", page_count: null, ready_at: null });
const FAILED = doc({ file_name: "broken.pdf", status: "failed", error_code: "corrupted", ready_at: null });
const DOCS = [A, B, C, BUSY, FAILED];
const summaryOf = (d: DocumentOut, overrides: Record<string, unknown> = {}) => ({
  document_id: d.id, status: "ready", pending: false, error_code: null, sections: [], citations: [], warnings: [], grounding: null, chunk_count: 1, model: "m", generated_at: "2026-11-26T10:00:00Z", ...overrides,
});

function backend(docs: DocumentOut[] = DOCS) {
  return signedInBackend()
    .on(`GET /courses/${COURSE_ID}`, () => json(200, course()))
    .on(`GET /courses/${COURSE_ID}/documents`, () => json(200, page(docs, 100)))
    .on(`GET /courses/${COURSE_ID}/summaries`, () => json(200, page([])))
    .on(`GET /courses/${COURSE_ID}/quizzes`, () => json(200, page([])))
    .match(/^GET \/documents\/[0-9a-f-]{36}\/summary$/, () => problem(404, "not_found"));
}
const open = (search = "") => renderPage(<Workspace courseId={COURSE_ID} />, { shell: "rail", path: `/courses/${COURSE_ID}`, search });
const materials = () => screen.getByRole("region", { name: "Materials" });
const previewName = (name: string) => new RegExp(`^Preview ${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`);
const box = (name: string) => within(materials()).getByRole("checkbox", { name: `Select ${name}` });
const user = () => userEvent.setup();

describe("WS-SEL multi-file selection in the Course Workspace", () => {
  it("WS-SEL-01 every row has a checkbox; only ready files can be checked; non-ready ones say why", async () => {
    backend();
    open();
    await screen.findByRole("heading", { level: 1, name: "Queueing Theory" });
    for (const d of [A, B, C]) expect(box(d.file_name)).toBeEnabled();
    for (const d of [BUSY, FAILED]) {
      expect(box(d.file_name)).toBeDisabled();
      expect(box(d.file_name)).toHaveAccessibleDescription(/Only ready files can be used/);
    }
    expect(screen.getByTestId("workspace-count")).toHaveTextContent("0 of 3 files selected");
    expect(screen.queryByTestId("selection-card")).toBeNull();
    expect(screen.getByTestId("batch-bar")).toHaveAttribute("data-open", "false");
  });

  it("WS-SEL-02 Select all checks ready files only; one change makes it mixed; Clear empties", async () => {
    backend();
    open();
    await screen.findByRole("heading", { level: 1, name: "Queueing Theory" });
    const all = screen.getByTestId("select-all") as HTMLInputElement;
    await user().click(all);
    expect(screen.getByTestId("workspace-count")).toHaveTextContent("3 of 3 files selected");
    for (const d of [A, B, C]) expect(box(d.file_name)).toBeChecked();
    for (const d of [BUSY, FAILED]) expect(box(d.file_name)).not.toBeChecked();
    expect(all.checked).toBe(true);
    await user().click(box(B.file_name));
    expect(all.indeterminate).toBe(true);
    expect(screen.getByTestId("workspace-count")).toHaveTextContent("2 of 3 files selected");
    await user().click(within(materials()).getByRole("button", { name: "Clear" }));
    expect(screen.getByTestId("workspace-count")).toHaveTextContent("0 of 3 files selected");
    expect(all.indeterminate).toBe(false);
  });

  it("WS-SEL-03 previewing and checking are separate: checking does not move the preview, previewing does not check", async () => {
    backend();
    open(`file=${C.id}`);
    await screen.findByRole("heading", { level: 1, name: "Queueing Theory" });
    const previewC = within(materials()).getByRole("link", { name: previewName(C.file_name) });
    expect(previewC).toHaveAttribute("aria-current", "true");
    expect(box(C.file_name)).not.toBeChecked();
    await user().click(box(A.file_name));
    expect(previewC).toHaveAttribute("aria-current", "true");
    expect(within(materials()).getByRole("link", { name: previewName(A.file_name) })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("region", { name: C.file_name })).toBeVisible(); // the details stay on the previewed file
  });

  it("WS-SEL-04 two checked: one combined summary POST with exactly those ids, then its page", async () => {
    const b = backend().on(`POST /courses/${COURSE_ID}/summaries`, () => json(202, { id: SUMMARY_ID, course_id: COURSE_ID, title: "Summary of 2 files", status: "generating", pending: true, error_code: null, source_documents: [], sections: [], citations: [], warnings: [], grounding: null, chunk_count: null, model: null, generated_at: null, created_at: "2026-11-26T10:00:00Z" }));
    open();
    await screen.findByRole("heading", { level: 1, name: "Queueing Theory" });
    await user().click(box(B.file_name));
    await user().click(box(A.file_name));
    const card = await screen.findByTestId("selection-card");
    expect(within(card).getByRole("heading", { name: "2 files selected" })).toBeVisible();
    expect(within(card).getByRole("button", { name: `Remove ${A.file_name} from the selection` })).toBeVisible();
    expect(screen.getByTestId("batch-bar")).toHaveAttribute("data-open", "true");
    await user().click(within(card).getByRole("button", { name: "Create combined summary" }));
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith(`/summaries/${SUMMARY_ID}`));
    const posts = b.calls.filter((c) => c.method === "POST" && c.path.endsWith("/summaries"));
    expect(posts).toHaveLength(1);
    expect(posts[0]!.body).toEqual({ document_ids: [B.id, A.id] }); // the reader's order, each once, never a non-ready file
  });

  it("WS-SEL-05 one checked: the file's own summary is requested and opened", async () => {
    const b = backend().on(`POST /documents/${C.id}/summary`, () => json(202, summaryOf(C, { status: "generating", pending: true })));
    open();
    await screen.findByRole("heading", { level: 1, name: "Queueing Theory" });
    await user().click(box(C.file_name));
    await user().click(within(await screen.findByTestId("selection-card")).getByRole("button", { name: "Create summary" }));
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith(`/courses/${COURSE_ID}/documents/${C.id}/summary`));
    expect(b.calls.filter((c) => c.method === "POST").map((c) => c.path)).toContain(`/documents/${C.id}/summary`);
  });

  it("WS-SEL-06 Create quiz hands the checked files to the Quiz page, which starts with them selected", async () => {
    backend();
    open();
    await screen.findByRole("heading", { level: 1, name: "Queueing Theory" });
    await user().click(box(A.file_name));
    await user().click(box(C.file_name));
    await user().click(within(await screen.findByTestId("selection-card")).getByRole("button", { name: "Create quiz" }));
    expect(nav.push).toHaveBeenCalledWith(`/courses/${COURSE_ID}/quizzes?from=workspace`);
    expect(takeHandoff(COURSE_ID, "quiz")).toEqual([A.id, C.id]);
    renderPage(<QuizListPage courseId={COURSE_ID} />, { shell: "rail", path: `/courses/${COURSE_ID}/quizzes`, search: "from=workspace" });
    expect(await screen.findByRole("button", { name: "Create quiz from 2 files" })).toBeEnabled();
  });

  it("WS-SEL-07 Ask selected materials hands the files to the chat, which sends them as document_ids", async () => {
    backend();
    open();
    await screen.findByRole("heading", { level: 1, name: "Queueing Theory" });
    await user().click(box(B.file_name));
    await user().click(within(await screen.findByTestId("selection-card")).getByRole("button", { name: "Ask selected materials" }));
    expect(nav.push).toHaveBeenCalledWith(`/courses/${COURSE_ID}/chat?from=workspace`);
    expect(takeHandoff(COURSE_ID, "chat")).toEqual([B.id]);
    const b = signedInBackend().on("POST /conversations/c-1/messages", () => json(200, {}));
    tokenStore.set("t", 900);
    await sendMessage("c-1", "What is a Jackson network?", [B.id, B.id]);
    expect(b.calls.find((c) => c.method === "POST")!.body).toEqual({ question: "What is a Jackson network?", document_ids: [B.id] });
    await sendMessage("c-1", "Anything?");
    expect(b.calls.filter((c) => c.method === "POST")[1]!.body).toEqual({ question: "Anything?" });
  });

  it("WS-SEL-08 keyboard: Space checks a row; the selection actions are reachable buttons", async () => {
    backend();
    open();
    await screen.findByRole("heading", { level: 1, name: "Queueing Theory" });
    box(A.file_name).focus();
    await user().keyboard(" ");
    expect(box(A.file_name)).toBeChecked();
    const card = await screen.findByTestId("selection-card");
    for (const name of ["Create summary", "Create quiz", "Ask selected materials", "Clear selection"]) {
      expect(within(card).getByRole("button", { name })).toBeEnabled();
    }
  });

  it("WS-SEL-09 the hand-off is per course, de-duplicated, expires, and is cleared on sign-out", () => {
    vi.useFakeTimers();
    try {
      handOff("course-a", "quiz", ["11111111-1111-4111-8111-000000000001", "11111111-1111-4111-8111-000000000001"]);
      expect(takeHandoff("course-a", "quiz")).toHaveLength(1);
      expect(takeHandoff("course-b", "quiz")).toEqual([]);
      vi.advanceTimersByTime(11 * 60 * 1000);
      expect(takeHandoff("course-a", "quiz")).toEqual([]);
      handOff("course-a", "chat", ["x"]);
      clearHandoffs();
      expect(takeHandoff("course-a", "chat")).toEqual([]);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("WS-SUM the previewed file's summary action follows the real summary state", () => {
  const details = () => screen.getByRole("region", { name: A.file_name });

  it("WS-SUM-01 no summary yet: Create summary (never Open summary) posts once and opens it", async () => {
    const b = backend().on(`POST /documents/${A.id}/summary`, () => json(202, summaryOf(A, { status: "generating", pending: true })));
    open();
    const create = await within(await screen.findByRole("region", { name: A.file_name })).findByRole("button", { name: "Create summary" });
    expect(within(details()).queryByRole("link", { name: "Open summary" })).toBeNull();
    await user().click(create);
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith(`/courses/${COURSE_ID}/documents/${A.id}/summary`));
    expect(b.calls.filter((c) => c.method === "POST" && c.path === `/documents/${A.id}/summary`)).toHaveLength(1);
  });

  it("WS-SUM-02 generating: Summary processing, no Open summary", async () => {
    backend().on(`GET /documents/${A.id}/summary`, () => json(200, summaryOf(A, { status: "generating", pending: true })));
    open();
    expect(await within(await screen.findByRole("region", { name: A.file_name })).findByRole("button", { name: /Summary processing/ })).toBeDisabled();
    expect(within(details()).queryByRole("link", { name: "Open summary" })).toBeNull();
  });

  it("WS-SUM-03 failed: the real reason and Retry summary", async () => {
    backend().on(`GET /documents/${A.id}/summary`, () => json(200, summaryOf(A, { status: "failed", error_code: "llm_unavailable" })));
    open();
    const panel = await screen.findByRole("region", { name: A.file_name });
    expect(await within(panel).findByText("The AI service is unavailable right now. Try again later.")).toBeVisible();
    expect(within(panel).getByRole("button", { name: "Retry summary" })).toBeEnabled();
  });

  it("WS-SUM-04 a server error while checking is called a server error, not a connection problem", async () => {
    backend().on(`GET /documents/${A.id}/summary`, () => problem(500, "internal_error"));
    open();
    const panel = await screen.findByRole("region", { name: A.file_name });
    expect(await within(panel).findByText("The server couldn’t load this summary")).toBeVisible();
    expect(within(panel).queryByText(/offline|Check your connection/i)).toBeNull();
  });
});

describe("WS-ERR the summary page names the real failure", () => {
  const openSummary = () => renderPage(<SummaryPage courseId={COURSE_ID} documentId={A.id} />, { shell: "rail", path: `/courses/${COURSE_ID}/documents/${A.id}/summary` });
  const base = () => signedInBackend().on(`GET /courses/${COURSE_ID}`, () => json(200, course())).on(`GET /documents/${A.id}`, () => json(200, A));

  it("WS-ERR-01 no summary yet (404) is not an error: it offers to create one", async () => {
    base().on(`GET /documents/${A.id}/summary`, () => problem(404, "not_found"));
    openSummary();
    expect(await screen.findByRole("heading", { name: "No summary yet" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Generate summary" })).toBeEnabled();
  });

  it("WS-ERR-02 a database behind the code (503 database_outdated) says the server needs an update", async () => {
    base().on(`GET /documents/${A.id}/summary`, () => problem(503, "database_outdated", "The server's database needs an update."));
    openSummary();
    expect(await screen.findByText("The server needs an update")).toBeVisible();
    expect(screen.queryByText(/Check your connection/)).toBeNull();
  });

  it("WS-ERR-03 a 500 is a server error; only a real network failure mentions the connection", async () => {
    const b = base().on(`GET /documents/${A.id}/summary`, () => problem(500, "internal_error"));
    openSummary();
    expect(await screen.findByText("The server couldn’t load this summary")).toBeVisible();
    b.on(`GET /documents/${A.id}/summary`, () => Promise.reject(new TypeError("Failed to fetch")));
    await user().click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("You appear to be offline")).toBeVisible();
  });
});
