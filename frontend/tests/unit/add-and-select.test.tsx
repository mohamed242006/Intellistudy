import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DocumentPicker } from "@/features/documents/components/DocumentPicker";
import { SELECTION_COPY, allState, prune, selectAll, selectedCountText, splitName, toggle } from "@/features/documents/selection";
import { CourseSummaryPage, groupByFile } from "@/features/summary/components/CourseSummaryPage";
import { CreateSummaryPage } from "@/features/summary/components/CreateSummaryPage";
import { UploadPage } from "@/features/upload/components/UploadPage";
import { tokenStore } from "@/lib/auth/token-store";
import type { CourseSummaryOut, DocumentOut } from "@/lib/api/types";
import { deferred, renderPage, signedInBackend } from "../helpers/app";
import { COURSE_ID, course, doc, page } from "../helpers/data";
import { json, problem } from "../helpers/fake-backend";
import { FakeXHR, installFakeXHR, xhrFor } from "../helpers/fake-xhr";
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

const SUMMARY_ID = "44444444-4444-4444-8444-444444444444";
const DOCS = `GET /courses/${COURSE_ID}/documents`;
const pdf = (name: string) => new File(["%PDF-1.4 body"], name, { type: "application/pdf" });
const user = () => userEvent.setup({ applyAccept: false });

function reducedMotion(on: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: on && query.includes("reduce"), media: query, addEventListener() {}, removeEventListener() {} }));
}

beforeEach(() => tokenStore.clear());
afterEach(() => vi.unstubAllGlobals());

// ------------------------------------------------------------------------------------------- Add materials
describe("ADD Add materials: stage, add explicitly, then leave smoothly", () => {
  const open = () => renderPage(<UploadPage courseId={COURSE_ID} />, { path: `/courses/${COURSE_ID}/upload` });
  const backend = () => signedInBackend().on(`GET /courses/${COURSE_ID}`, () => json(200, course())).on(DOCS, () => json(200, page([], 100)));
  const input = (container: HTMLElement) => container.querySelector<HTMLInputElement>("input[type=file]")!;

  it("ADD-03 empty queue: no Add button; one file: “Add this file”; nothing is sent before it is pressed", async () => {
    installFakeXHR();
    backend();
    const { container } = open();
    await screen.findByText("0 files");
    expect(screen.queryByTestId("add-files")).toBeNull();
    await user().upload(input(container), [pdf("a.pdf")]);
    expect(await screen.findByRole("button", { name: "Add this file" })).toBeEnabled();
    expect(screen.getByText("Selected")).toBeVisible();
    expect(screen.getByText("Nothing is uploaded until you add the files.")).toBeVisible();
    await act(async () => new Promise((r) => setTimeout(r, 30)));
    expect(FakeXHR.all).toHaveLength(0);
  });

  it("ADD-04 several valid files: “Add these files”; an invalid file gets its own row and is not counted or sent", async () => {
    installFakeXHR();
    backend();
    const { container } = open();
    await screen.findByText("0 files");
    await user().upload(input(container), [pdf("a.pdf"), new File(["x"], "notes.txt"), pdf("b.pdf")]);
    const add = await screen.findByRole("button", { name: "Add these files" });
    expect(screen.getByText("This file type isn’t supported. Upload PDF, Word (.docx) or PowerPoint (.pptx).")).toBeVisible();
    await user().upload(input(container), [new File(["\u0000\u0000\u0000\u0018ftypmp42"], "video.pptx")]); // renamed video
    expect(await screen.findByText(/doesn’t match its extension/)).toBeVisible();
    expect(add).toHaveAccessibleName("Add these files"); // still two valid files
    await user().click(add);
    await waitFor(() => expect(FakeXHR.all).toHaveLength(1));
    expect(screen.getByTestId("add-files")).toHaveTextContent("Adding 2 files…");
    expect(xhrFor("notes.txt")).toBeUndefined();
  });

  it("ADD-05 all accepted: success state, then client navigation to the course (reduced motion: immediately)", async () => {
    reducedMotion(true);
    installFakeXHR();
    backend();
    const href = window.location.href;
    const { container } = open();
    await screen.findByText("0 files");
    await user().upload(input(container), [pdf("a.pdf"), pdf("b.pdf")]);
    await user().click(await screen.findByRole("button", { name: "Add these files" }));
    await waitFor(() => expect(xhrFor("a.pdf")).toBeDefined());
    act(() => xhrFor("a.pdf")!.respond(202, { documents: [{ ...doc({ file_name: "a.pdf", status: "queued" }), duplicate: false }] }));
    expect(nav.push).not.toHaveBeenCalled(); // not before every file is accepted
    await waitFor(() => expect(xhrFor("b.pdf")).toBeDefined());
    act(() => xhrFor("b.pdf")!.respond(202, { documents: [{ ...doc({ file_name: "b.pdf", status: "queued" }), duplicate: false }] }));
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith(`/courses/${COURSE_ID}`));
    expect(nav.push).toHaveBeenCalledTimes(1);
    expect(screen.getAllByText("2 files added. Processing has started.").length).toBeGreaterThan(0);
    expect(window.location.href).toBe(href); // the router navigated; the document was never reloaded
  });

  it("ADD-06 with motion, the page plays the exit transition (success first) and then navigates", async () => {
    reducedMotion(false);
    installFakeXHR();
    backend();
    const { container } = open();
    await screen.findByText("0 files");
    await user().upload(input(container), [pdf("only.pdf")]);
    await user().click(await screen.findByRole("button", { name: "Add this file" }));
    await waitFor(() => expect(xhrFor("only.pdf")).toBeDefined());
    act(() => xhrFor("only.pdf")!.respond(202, { documents: [{ ...doc({ file_name: "only.pdf", status: "queued" }), duplicate: false }] }));
    expect(await screen.findByRole("button", { name: "1 file added" })).toBeDisabled();
    expect(container.querySelector(".motion-leave")).not.toBeNull();
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith(`/courses/${COURSE_ID}`), { timeout: 2000 });
  });

  it("ADD-07 partial failure: counts, failed row kept with Retry and Remove, focus on the outcome, Continue is explicit", async () => {
    installFakeXHR();
    backend();
    const { container } = open();
    await screen.findByText("0 files");
    await user().upload(input(container), [pdf("ok.pdf"), pdf("flaky.pdf")]);
    await user().click(await screen.findByRole("button", { name: "Add these files" }));
    await waitFor(() => expect(xhrFor("ok.pdf")).toBeDefined());
    act(() => xhrFor("ok.pdf")!.respond(202, { documents: [{ ...doc({ file_name: "ok.pdf", status: "queued" }), duplicate: false }] }));
    await waitFor(() => expect(xhrFor("flaky.pdf")).toBeDefined());
    act(() => xhrFor("flaky.pdf")!.fail());
    expect(await screen.findByText("1 file added · 1 file failed")).toBeVisible();
    expect(screen.getByRole("button", { name: "Retry flaky.pdf" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Remove flaky.pdf" })).toBeVisible();
    await waitFor(() => expect(screen.getByText("1 file added · 1 file failed").closest("[role=status]")).toHaveFocus());
    expect(nav.push).not.toHaveBeenCalled();
    // retry: the same row goes back to the queue
    await user().click(screen.getByRole("button", { name: "Retry flaky.pdf" }));
    await waitFor(() => expect(FakeXHR.all.filter((x) => x === xhrFor("flaky.pdf"))).toHaveLength(1));
    await waitFor(() => expect(FakeXHR.all).toHaveLength(3));
    act(() => FakeXHR.all[2]!.fail());
    await user().click(await screen.findByRole("button", { name: "Continue with uploaded files" }));
    expect(nav.push).toHaveBeenCalledWith(`/courses/${COURSE_ID}`);
  });

  it("ADD-08 leaving with staged files asks first (Stay focused); nothing is asked when the queue is empty", async () => {
    installFakeXHR();
    backend();
    window.history.pushState({}, "", `/courses/${COURSE_ID}/upload`); // the browser's own location, as in the app
    const { container } = open();
    await screen.findByText("0 files");
    const before = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(before);
    expect(before.defaultPrevented).toBe(false); // empty queue: no warning
    await user().upload(input(container), [pdf("draft.pdf")]);
    await screen.findByRole("button", { name: "Add this file" });
    const unload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(unload);
    expect(unload.defaultPrevented).toBe(true);
    await user().click(within(screen.getByRole("navigation", { name: "Breadcrumb" })).getByRole("link", { name: "Courses" }));
    const dialog = await screen.findByRole("dialog", { name: "Leave without adding your files?" });
    expect(dialog).toHaveTextContent("1 selected file hasn’t been added yet.");
    expect(within(dialog).getByRole("button", { name: "Stay on this page" })).toHaveFocus();
    expect(nav.push).not.toHaveBeenCalled();
    await user().click(within(dialog).getByRole("button", { name: "Stay on this page" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    await user().click(within(screen.getByRole("navigation", { name: "Breadcrumb" })).getByRole("link", { name: "Courses" }));
    await user().click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Leave anyway" }));
    expect(nav.push).toHaveBeenCalledWith("/#courses");
    window.history.pushState({}, "", "/");
  });
});

// -------------------------------------------------------------------------------------- document picker
const READY_A = doc({ file_name: "Lecture 1 — Introduction.pdf" });
const LONG = doc({ file_name: `${"Very long lecture title about queueing networks and ".repeat(4)}final.pptx`, file_type: "pptx", page_count: 12 });
const BUSY = doc({ file_name: "busy.docx", file_type: "docx", status: "embedding", page_count: null, ready_at: null });
const BROKEN = doc({ file_name: "broken.pdf", status: "failed", error_code: "corrupted", ready_at: null });
const DOCS_ALL = [READY_A, LONG, BUSY, BROKEN];

function Harness({ initial = [] as string[], documents = DOCS_ALL as DocumentOut[] }) {
  const [selected, setSelected] = useState<string[]>(initial);
  return (
    <>
      <DocumentPicker legend="Files" documents={documents} selected={selected} onChange={setSelected} />
      <output data-testid="ids">{selected.join(",")}</output>
    </>
  );
}

describe("SEL reusable document selection", () => {
  it("SEL-01 pure rules: ready only, order kept, no duplicates, stale ids dropped and reported", () => {
    expect(selectAll(DOCS_ALL)).toEqual([READY_A.id, LONG.id]);
    expect(toggle([], BUSY.id, true, DOCS_ALL)).toEqual([]);
    expect(toggle([LONG.id], READY_A.id, true, DOCS_ALL)).toEqual([LONG.id, READY_A.id]);
    expect(toggle([LONG.id], LONG.id, true, DOCS_ALL)).toEqual([LONG.id]);
    expect(allState([], DOCS_ALL)).toBe("none");
    expect(allState([LONG.id], DOCS_ALL)).toBe("some");
    expect(allState([LONG.id, READY_A.id], DOCS_ALL)).toBe("all");
    const failedNow = DOCS_ALL.map((d) => (d.id === LONG.id ? { ...d, status: "failed" } : d));
    expect(prune([READY_A.id, LONG.id, "gone"], failedNow)).toEqual({ kept: [READY_A.id], dropped: [LONG.id, "gone"] });
    expect([selectedCountText(1), selectedCountText(3), selectedCountText(0)]).toEqual(["1 file selected", "3 files selected", "0 files selected"]);
    expect([SELECTION_COPY.createSummary(1), SELECTION_COPY.createSummary(3), SELECTION_COPY.createQuiz(1), SELECTION_COPY.createQuiz(3)]).toEqual([
      "Create summary from 1 file",
      "Create summary from 3 files",
      "Create quiz from 1 file",
      "Create quiz from 3 files",
    ]);
    expect(splitName("notes.final.pptx")).toEqual({ stem: "notes.final", ext: ".pptx" });
    expect(splitName("README")).toEqual({ stem: "README", ext: "" });
  });

  it("SEL-02 select all picks ready files only; one change makes it indeterminate; Clear empties", async () => {
    render(<Harness />);
    const all = screen.getByRole("checkbox", { name: "Select all ready files" }) as HTMLInputElement;
    expect(screen.getByRole("checkbox", { name: "busy.docx, Processing" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "broken.pdf, Processing failed" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Clear selection" })).toBeDisabled();
    await user().click(all);
    expect(screen.getByTestId("ids")).toHaveTextContent(`${READY_A.id},${LONG.id}`);
    expect(all.checked).toBe(true);
    expect(screen.getByTestId("selected-count")).toHaveTextContent("2 files selected");
    await user().click(screen.getByRole("checkbox", { name: READY_A.file_name }));
    expect(all.indeterminate).toBe(true);
    expect(all.checked).toBe(false);
    expect(screen.getByTestId("selected-count")).toHaveTextContent("1 file selected");
    await user().click(screen.getByRole("button", { name: "Clear selection" }));
    expect(screen.getByTestId("ids")).toHaveTextContent("");
    expect(all.indeterminate).toBe(false);
  });

  it("SEL-03 keyboard: Tab reaches the checkboxes and Space toggles them", async () => {
    render(<Harness />);
    const first = screen.getByRole("checkbox", { name: READY_A.file_name });
    first.focus();
    await user().keyboard(" ");
    expect(first).toBeChecked();
    await user().tab();
    expect(screen.getByRole("checkbox", { name: LONG.file_name })).toHaveFocus();
    await user().keyboard(" ");
    expect(screen.getByTestId("ids")).toHaveTextContent(`${READY_A.id},${LONG.id}`);
  });

  it("SEL-04 long names truncate their stem, keep the extension, expose the full name; no break-all", () => {
    const { container } = render(<Harness />);
    const row = screen.getByRole("checkbox", { name: LONG.file_name }).closest("label")!;
    expect(row).toHaveAttribute("title", LONG.file_name);
    expect(row.querySelector(".truncate")).not.toBeNull();
    expect(within(row).getByText(".pptx")).toBeVisible();
    expect(row).toHaveTextContent("PPTX · 12 slides · 3.1 MB");
    expect(container.querySelector(".break-all")).toBeNull();
  });

  it("SEL-05 empty states: no files, no ready files", () => {
    const { rerender } = render(<Harness documents={[]} />);
    expect(screen.getByText("This course has no files yet.")).toBeVisible();
    rerender(<Harness documents={[BUSY]} />);
    expect(screen.getByText(/No file is ready yet/)).toBeVisible();
    expect(screen.queryByRole("checkbox", { name: "Select all ready files" })).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------- summaries
function combined(overrides: Partial<CourseSummaryOut> = {}): CourseSummaryOut {
  return {
    id: SUMMARY_ID,
    course_id: COURSE_ID,
    title: "Summary of 2 files",
    status: "ready",
    pending: false,
    error_code: null,
    source_documents: [{ document_id: READY_A.id, file_name: READY_A.file_name }, { document_id: LONG.id, file_name: LONG.file_name }],
    sections: [
      { heading: "Arrivals", text: "Arrivals follow a Poisson process [1].", citations: [1], source_range: { kind: "page", start: 2, end: 2 }, document_id: READY_A.id, file_name: READY_A.file_name },
      { heading: "Networks", text: "Jackson networks decompose into stations [2].", citations: [2], source_range: { kind: "slide", start: 4, end: 4 }, document_id: LONG.id, file_name: LONG.file_name },
    ],
    citations: [
      { number: 1, document_id: READY_A.id, file_name: READY_A.file_name, citation_label: "p. 2", page: 2, slide: null, passage: "Arrivals follow a Poisson process." },
      { number: 2, document_id: LONG.id, file_name: LONG.file_name, citation_label: "Slide 4", page: null, slide: 4, passage: "Jackson networks decompose." },
    ],
    warnings: [],
    grounding: { checked: 2, supported: 2, removed: 0 },
    chunk_count: 2,
    model: "m",
    generated_at: "2026-11-26T10:00:00Z",
    created_at: "2026-11-26T10:00:00Z",
    ...overrides,
  };
}

describe("SUM create one summary from selected files", () => {
  const base = () =>
    signedInBackend()
      .on(`GET /courses/${COURSE_ID}`, () => json(200, course()))
      .on(DOCS, () => json(200, page(DOCS_ALL, 100)))
      .on(`GET /courses/${COURSE_ID}/summaries`, () => json(200, page([])));
  const open = (search = "") => renderPage(<CreateSummaryPage courseId={COURSE_ID} />, { shell: "rail", path: `/courses/${COURSE_ID}/summaries`, search });

  it("SUM-01 nothing selected: disabled with guidance; several files: one POST with the exact ids once each", async () => {
    const hold = deferred<void>();
    const b = base().on(`POST /courses/${COURSE_ID}/summaries`, () => hold.promise.then(() => json(202, combined({ status: "generating", pending: true, sections: [], citations: [] }))));
    open();
    expect(await screen.findByRole("button", { name: "Create summary from 0 files" })).toBeDisabled();
    expect(screen.getAllByText("Select at least one ready file to create a summary.").length).toBeGreaterThan(0);
    await user().click(screen.getByRole("checkbox", { name: "Select all ready files" }));
    const submit = screen.getByRole("button", { name: "Create summary from 2 files" });
    await user().click(submit);
    await user().click(submit);
    const posts = b.calls.filter((c) => c.method === "POST" && c.path.endsWith("/summaries"));
    expect(posts).toHaveLength(1);
    expect(posts[0]!.body).toEqual({ document_ids: [READY_A.id, LONG.id] }); // never the processing or failed file
    expect(screen.getByRole("checkbox", { name: READY_A.file_name })).toBeDisabled(); // selection locked while sending
    hold.resolve();
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith(`/summaries/${SUMMARY_ID}`));
  });

  it("SUM-02 a refusal keeps the selection for a retry; ?document= preselects and one file uses its own summary", async () => {
    const b = base().on(`POST /courses/${COURSE_ID}/summaries`, () => problem(409, "document_not_ready", "x"));
    open();
    await user().click(await screen.findByRole("checkbox", { name: READY_A.file_name }));
    await user().click(screen.getByRole("checkbox", { name: LONG.file_name }));
    await user().click(screen.getByRole("button", { name: "Create summary from 2 files" }));
    expect(await screen.findByText(/This file isn’t ready yet/)).toBeVisible();
    expect(screen.getByRole("checkbox", { name: READY_A.file_name })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: LONG.file_name })).toBeChecked();
    expect(b.calls.filter((c) => c.method === "POST" && c.path.endsWith("/summaries"))).toHaveLength(1);
  });

  it("SUM-03 ?document= preselects that file; with one file the document's own summary is used (deep links kept)", async () => {
    const b = base().on(`POST /documents/${READY_A.id}/summary`, () => json(202, { document_id: READY_A.id, status: "generating", pending: true, error_code: null, sections: [], citations: [], warnings: [], grounding: null, chunk_count: null, model: null, generated_at: null }));
    open(`document=${READY_A.id}`);
    expect(await screen.findByRole("checkbox", { name: READY_A.file_name })).toBeChecked();
    expect(screen.getByText("With one file, you get that file’s summary page.")).toBeVisible();
    await user().click(screen.getByRole("button", { name: "Create summary from 1 file" }));
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith(`/courses/${COURSE_ID}/documents/${READY_A.id}/summary`));
    expect(b.calls.filter((c) => c.method === "POST" && !c.path.startsWith("/auth")).map((c) => c.path)).toEqual([`/documents/${READY_A.id}/summary`]);
  });

  it("SUM-04 the combined summary shows its source files and groups sections and citations by file", async () => {
    signedInBackend().on(`GET /summaries/${SUMMARY_ID}`, () => json(200, combined())).on(`GET /courses/${COURSE_ID}`, () => json(200, course()));
    renderPage(<CourseSummaryPage summaryId={SUMMARY_ID} />, { shell: "rail", path: `/summaries/${SUMMARY_ID}` });
    expect(await screen.findByRole("heading", { level: 1, name: "Summary of 2 files" })).toBeVisible();
    expect(screen.getByText("Combined summary")).toBeVisible();
    expect(screen.getByText(/From 2 files/)).toBeVisible();
    const files = screen.getByRole("region", { name: "SOURCE FILES" });
    expect(within(files).getByRole("link", { name: `Open ${READY_A.file_name}` })).toHaveAttribute("href", `/courses/${COURSE_ID}?file=${READY_A.id}`);
    for (const name of [READY_A.file_name, LONG.file_name]) {
      const group = screen.getByRole("region", { name });
      expect(within(group).getByRole("heading", { level: 2, name })).toBeVisible();
    }
    expect(within(screen.getByRole("region", { name: READY_A.file_name })).getByRole("heading", { level: 3, name: /Arrivals/ })).toBeVisible();
    expect(groupByFile(combined()).map((g) => g.fileName)).toEqual([READY_A.file_name, LONG.file_name]);
  });

  it("SUM-05 an invalid summary id is never requested", async () => {
    const b = signedInBackend();
    renderPage(<CourseSummaryPage summaryId="not-an-id" />, { shell: "rail", path: "/summaries/not-an-id" });
    expect(await screen.findByRole("heading", { name: "Not found" })).toBeVisible();
    expect(b.calls.filter((c) => c.path.startsWith("/summaries"))).toEqual([]);
  });
});
