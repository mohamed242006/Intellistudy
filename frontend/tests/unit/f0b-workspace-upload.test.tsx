import { focusManager } from "@tanstack/react-query";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MAX_POLL_FAILURES } from "@/features/documents/polling";
import { UploadPage } from "@/features/upload/components/UploadPage";
import { Workspace } from "@/features/workspace/components/Workspace";
import { tokenStore } from "@/lib/auth/token-store";
import { deferred, renderPage, signedInBackend } from "../helpers/app";
import { COURSE_ID, HOSTILE, OTHER_ID, course, doc, page } from "../helpers/data";
import { json, problem } from "../helpers/fake-backend";
import { FakeXHR, installFakeXHR, xhrFor } from "../helpers/fake-xhr";
import { nav } from "../helpers/navigation";

vi.mock("next/navigation", async () => (await import("../helpers/navigation")).navigationMock());
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode; scroll?: boolean }) => {
    const attributes: Record<string, unknown> = { ...rest };
    delete attributes.scroll; // a next/link option, not an anchor attribute
    return (
      <a href={href} {...attributes}>
        {children}
      </a>
    );
  },
}));

beforeEach(() => tokenStore.clear());
afterEach(() => {
  vi.useRealTimers();
  focusManager.setFocused(undefined);
});

const DOCS = `GET /courses/${COURSE_ID}/documents`;
const workspace = (search = "") => renderPage(<Workspace courseId={COURSE_ID} />, { shell: "rail", path: `/courses/${COURSE_ID}`, search });
const upload = () => renderPage(<UploadPage courseId={COURSE_ID} />, { path: `/courses/${COURSE_ID}/upload` });
/** Selecting files only stages them; the explicit "Add this file / Add these files" submits them. */
const addFiles = async () => userEvent.click(await screen.findByRole("button", { name: /^Add (this file|these files)$/ }));
const tick = async (ms = 2000) => act(async () => {
  vi.advanceTimersByTime(ms);
});
const user = () => userEvent.setup({ applyAccept: false });
const pdf = (name: string, size = 1000) => Object.defineProperty(new File(["%PDF-1.4"], name, { lastModified: size }), "size", { value: size });

describe("GF0B-10 Course Workspace", () => {
  it("GF0B-10 shows the course, real file stats, the Materials list with checkboxes and the previewed file's details", async () => {
    const ready = doc({ file_name: "lecture-1.pdf", page_count: 48, size_bytes: 3_100_000 });
    const busy = doc({ file_name: "lecture-2.pdf", status: "extracting", page_count: null, ready_at: null });
    const broken = doc({ file_name: "notes.docx", file_type: "docx", status: "failed", error_code: "corrupted", page_count: null, ready_at: null });
    signedInBackend()
      .on(`GET /courses/${COURSE_ID}`, () => json(200, course()))
      .on(DOCS, () => json(200, page([ready, busy, broken], 100)))
      .on(`GET /courses/${COURSE_ID}/summaries`, () => json(200, page([])))
      .on(`GET /courses/${COURSE_ID}/quizzes`, () => json(200, page([])))
      .on(`GET /documents/${ready.id}/summary`, () => json(200, { document_id: ready.id, status: "ready", pending: false, error_code: null, sections: [], citations: [], warnings: [], grounding: null, chunk_count: 1, model: "m", generated_at: "2026-11-25T10:00:00Z" }));
    workspace();
    expect(await screen.findByRole("heading", { level: 1, name: "Queueing Theory" })).toBeVisible();
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByRole("link", { name: "Courses" })).toHaveAttribute("href", "/#courses");
    expect(await screen.findByText("Ready · 1 processing")).toBeVisible();
    expect(screen.getByTestId("workspace-count")).toHaveTextContent("0 of 1 file selected");
    const materials = screen.getByRole("region", { name: "Materials" });
    expect(within(materials).getAllByRole("listitem")).toHaveLength(3);
    expect(within(materials).getByRole("link", { name: /^Preview lecture-1\.pdf/ })).toHaveAttribute("aria-current", "true");
    expect(within(materials).getByRole("checkbox", { name: "Select lecture-1.pdf" })).toBeEnabled();
    const disabled = within(materials).getByRole("checkbox", { name: "Select lecture-2.pdf" });
    expect(disabled).toBeDisabled();
    expect(disabled).toHaveAccessibleDescription(/Can’t be selected: extracting/);
    const details = screen.getByRole("region", { name: "lecture-1.pdf" });
    expect(within(details).getByText("3.1 MB")).toBeVisible();
    expect(within(details).getByText("48")).toBeVisible();
    expect(within(details).getByRole("button", { name: "Download" })).toBeVisible();
    expect(within(details).queryByRole("button", { name: "Retry" })).toBeNull();
    expect(document.body.textContent).not.toMatch(/mastery|Topics found|OCR/i);
    expect(within(details).getByRole("link", { name: "Generate quiz" })).toHaveAttribute("href", `/courses/${COURSE_ID}/quizzes?document=${ready.id}`);
    expect(screen.getByRole("link", { name: "Ask your materials" })).toHaveAttribute("href", `/courses/${COURSE_ID}/chat`);
    // a summary exists, so (and only then) the panel offers to open it
    expect(await within(details).findByRole("link", { name: "Open summary" })).toHaveAttribute("href", `/courses/${COURSE_ID}/documents/${ready.id}/summary`);
    expect(screen.getAllByRole("link", { name: "Courses" }).some((a) => a.getAttribute("aria-current") === "page")).toBe(true);
  });

  it("GF0B-10 ?file= selects a file, including one beyond the loaded page; another course's file is not shown", async () => {
    const target = doc({ file_name: "far-away.pdf" });
    const foreign = doc({ course_id: OTHER_ID, file_name: "elsewhere.pdf" });
    signedInBackend()
      .on(`GET /courses/${COURSE_ID}`, () => json(200, course()))
      .on(DOCS, () => json(200, page([doc()], 100)))
      .on(`GET /documents/${target.id}`, () => json(200, target))
      .on(`GET /documents/${foreign.id}`, () => json(200, foreign));
    const view = workspace(`file=${target.id}`);
    expect(await screen.findByRole("region", { name: "far-away.pdf" })).toBeVisible();
    view.unmount();
    workspace(`file=${foreign.id}`);
    expect(await screen.findByText("This file no longer exists.")).toBeVisible();
    expect(screen.queryByText("elsewhere.pdf")).toBeNull();
  });

  it("GF0B-10 an empty course offers Upload files", async () => {
    signedInBackend().on(`GET /courses/${COURSE_ID}`, () => json(200, course())).on(DOCS, () => json(200, page([], 100)));
    workspace();
    expect(await screen.findByRole("heading", { name: "No materials yet" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Upload files" })).toHaveAttribute("href", `/courses/${COURSE_ID}/upload`);
  });
});

describe("GF0B-11 not found without leaks", () => {
  it("GF0B-11 a missing, foreign or malformed course id shows the same not-found state and nothing about the course", async () => {
    const bodies: string[] = [];
    for (const id of [OTHER_ID, "not-a-uuid"]) {
      signedInBackend()
        .on(`GET /courses/${id}`, () => problem(404, "not_found", "Resource not found."))
        .on(`GET /courses/${id}/documents`, () => problem(404, "not_found", "Resource not found."));
      const view = renderPage(<Workspace courseId={id} />, { shell: "rail" });
      expect(await screen.findByRole("heading", { level: 1, name: "Course not found" })).toBeVisible();
      bodies.push(screen.getByRole("main").textContent ?? "");
      view.unmount();
    }
    expect(bodies[0]).toBe(bodies[1]);
    expect(bodies[0]).not.toMatch(/Queueing|file|404|not_found/i);
  });
});

describe("GF0B-12 rename course", () => {
  it("GF0B-12 PATCHes the trimmed name and updates the page", async () => {
    const backend = signedInBackend()
      .on(`GET /courses/${COURSE_ID}`, () => json(200, course()))
      .on(DOCS, () => json(200, page([], 100)))
      .on(`PATCH /courses/${COURSE_ID}`, () => json(200, course({ name: "Queueing Networks" })));
    workspace();
    await userEvent.click(await screen.findByRole("button", { name: "Rename" }));
    const input = within(screen.getByRole("dialog", { name: "Rename course" })).getByLabelText("Course name");
    expect(input).toHaveValue("Queueing Theory");
    await userEvent.clear(input);
    await userEvent.type(input, " Queueing Networks ");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Queueing Networks" })).toBeVisible();
    expect(backend.calls.find((c) => c.method === "PATCH")!.body).toEqual({ name: "Queueing Networks" });
    expect(await screen.findByText("Course renamed.")).toBeVisible();
  });
});

describe("GF0B-13 delete course", () => {
  it("GF0B-13 confirms with the real file count, starts on Cancel, deletes, clears the caches and goes to the Dashboard", async () => {
    const backend = signedInBackend()
      .on(`GET /courses/${COURSE_ID}`, () => json(200, course()))
      .on(DOCS, () => json(200, page([doc(), doc()], 100)))
      .on(`DELETE /courses/${COURSE_ID}`, () => new Response(null, { status: 204 }));
    const { queryClient } = workspace();
    expect(await screen.findByTestId("workspace-count")).toHaveTextContent("0 of 2 files selected");
    await userEvent.click(screen.getByRole("button", { name: "Delete course" }));
    const dialog = screen.getByRole("dialog", { name: "Delete this course?" });
    expect(dialog).toHaveAccessibleDescription("This removes 2 files, their summaries, chat history and quiz results. This can’t be undone.");
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    expect(backend.count(`DELETE /courses/${COURSE_ID}`)).toBe(0);
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete course" }));
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/"));
    expect(queryClient.getQueryData(["course", COURSE_ID])).toBeUndefined();
    expect(queryClient.getQueriesData({ queryKey: ["documents", COURSE_ID] })).toEqual([]);
    expect(await screen.findByText("Course deleted.")).toBeVisible();
  });
});

describe("GF0B-20 retry", () => {
  it("GF0B-20 retries a Failed file once (repeat presses ignored) and shows it as Extracting", async () => {
    const failed = doc({ file_name: "notes.pdf", status: "failed", error_code: "timed_out", ready_at: null });
    const hold = deferred<void>();
    const backend = signedInBackend()
      .on(`GET /courses/${COURSE_ID}`, () => json(200, course()))
      .on(DOCS, () => json(200, page([failed], 100)))
      .on(`POST /documents/${failed.id}/retry`, () => hold.promise.then(() => json(202, { ...failed, status: "queued", error_code: null })));
    workspace();
    const retry = await screen.findByRole("button", { name: "Retry notes.pdf" });
    await userEvent.click(retry);
    await userEvent.click(retry);
    await userEvent.click(within(screen.getByRole("region", { name: "notes.pdf" })).getByRole("button", { name: "Retry" }));
    expect(backend.count(`POST /documents/${failed.id}/retry`)).toBe(1);
    hold.resolve();
    expect(await within(screen.getByRole("region", { name: "Materials" })).findByText("Extracting")).toBeVisible();
  });

  it("GF0B-20 a rejected retry shows the mapped message, not the problem body", async () => {
    const failed = doc({ file_name: "notes.pdf", status: "failed", error_code: "timed_out", ready_at: null });
    signedInBackend()
      .on(`GET /courses/${COURSE_ID}`, () => json(200, course()))
      .on(DOCS, () => json(200, page([failed], 100)))
      .on(`POST /documents/${failed.id}/retry`, () => problem(429, "queue_full", "Too many documents are still processing. Try again later."));
    workspace();
    await userEvent.click(await screen.findByRole("button", { name: "Retry notes.pdf" }));
    expect(await screen.findByText("Too many documents are still processing. Try again later.")).toBeVisible();
  });
});

describe("GF0B-21 delete document", () => {
  it("GF0B-21 confirms, disables repeat presses, and removes the file only after the 204", async () => {
    const target = doc({ file_name: "old.pdf" });
    const hold = deferred<void>();
    let stored = [target];
    const backend = signedInBackend()
      .on(`GET /courses/${COURSE_ID}`, () => json(200, course()))
      .on(DOCS, () => json(200, page(stored, 100)))
      .on(`DELETE /documents/${target.id}`, () =>
        hold.promise.then(() => {
          stored = [];
          return new Response(null, { status: 204 });
        }),
      );
    workspace();
    await userEvent.click(await screen.findByRole("button", { name: "Delete file" }));
    const dialog = screen.getByRole("dialog", { name: "Delete this file?" });
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    const confirm = within(dialog).getByRole("button", { name: "Delete file" });
    await userEvent.click(confirm);
    await userEvent.click(confirm);
    expect(confirm).toHaveAttribute("aria-busy", "true");
    expect(backend.count(`DELETE /documents/${target.id}`)).toBe(1);
    expect(within(screen.getByRole("region", { name: "Materials" })).getByRole("link", { name: /^Preview old\.pdf/ })).toBeVisible();
    hold.resolve();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(within(screen.getByRole("region", { name: "Materials" })).queryByRole("link", { name: /^Preview old\.pdf/ })).toBeNull());
    expect(await screen.findByText("File deleted.")).toBeVisible();
  });

  it("GF0B-21 a 404 (already deleted, or never this user's) is treated as deleted", async () => {
    const target = doc({ file_name: "gone.pdf" });
    let stored = [target];
    signedInBackend()
      .on(`GET /courses/${COURSE_ID}`, () => json(200, course()))
      .on(DOCS, () => json(200, page(stored, 100)))
      .on(`DELETE /documents/${target.id}`, () => {
        stored = [];
        return problem(404, "not_found", "Resource not found.");
      });
    workspace();
    await userEvent.click(await screen.findByRole("button", { name: "Delete file" }));
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete file" }));
    await waitFor(() => expect(within(screen.getByRole("region", { name: "Materials" })).queryByText("gone.pdf")).toBeNull());
  });
});

describe("GF0B-22 download from the workspace", () => {
  it("GF0B-22 saves the attachment under its server name and revokes the object URL", async () => {
    const target = doc({ file_name: "slides.pptx", file_type: "pptx" });
    const create = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:x");
    const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    signedInBackend()
      .on(`GET /courses/${COURSE_ID}`, () => json(200, course()))
      .on(DOCS, () => json(200, page([target], 100)))
      .on(`GET /documents/${target.id}/file`, () => new Response("PK", { status: 200, headers: { "content-disposition": "attachment; filename*=UTF-8''slides.pptx" } }));
    workspace();
    await userEvent.click(await screen.findByRole("button", { name: "Download" }));
    await waitFor(() => expect(click).toHaveBeenCalledOnce());
    expect((click.mock.instances[0] as unknown as HTMLAnchorElement).download).toBe("slides.pptx");
    expect(create).toHaveBeenCalledOnce();
    await waitFor(() => expect(revoke).toHaveBeenCalledWith("blob:x"), { timeout: 2000 });
  });

  it("GF0B-22 a failed download shows a safe message", async () => {
    const target = doc({ file_name: "slides.pptx" });
    signedInBackend()
      .on(`GET /courses/${COURSE_ID}`, () => json(200, course()))
      .on(DOCS, () => json(200, page([target], 100)))
      .on(`GET /documents/${target.id}/file`, () => problem(404, "not_found", "Resource not found."));
    workspace();
    await userEvent.click(await screen.findByRole("button", { name: "Download" }));
    expect(await screen.findByText("This file no longer exists.")).toBeVisible();
  });
});

describe("GF0B-19 polling", () => {
  it("GF0B-19 polls every 2 s while a document is in progress and stops once all are terminal", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    let current = doc({ file_name: "a.pdf", status: "embedding", ready_at: null });
    const backend = signedInBackend()
      .on(`GET /courses/${COURSE_ID}`, () => json(200, course()))
      .on(DOCS, () => json(200, page([current], 100)));
    workspace();
    const materials = await screen.findByRole("region", { name: "Materials" });
    expect(await within(materials).findByText("Extracting")).toBeVisible();
    const initial = backend.count(DOCS);
    await tick(1999);
    expect(backend.count(DOCS)).toBe(initial);
    current = { ...current, status: "ready", ready_at: "2026-11-25T10:02:00Z" };
    await tick(1);
    await waitFor(() => expect(backend.count(DOCS)).toBe(initial + 1));
    expect(await within(materials).findByText("Indexed")).toBeVisible();
    await tick();
    await tick();
    expect(backend.count(DOCS)).toBe(initial + 1);
  });

  it("GF0B-19 does not poll while the tab is hidden, and resumes when visible", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    const busy = doc({ status: "queued", ready_at: null });
    const backend = signedInBackend().on(`GET /courses/${COURSE_ID}`, () => json(200, course())).on(DOCS, () => json(200, page([busy], 100)));
    workspace();
    await within(await screen.findByRole("region", { name: "Materials" })).findByText("Extracting");
    const initial = backend.count(DOCS);
    act(() => focusManager.setFocused(false));
    await tick();
    await tick();
    expect(backend.count(DOCS)).toBe(initial);
    act(() => focusManager.setFocused(true));
    await tick();
    await waitFor(() => expect(backend.count(DOCS)).toBeGreaterThan(initial));
  });

  it("GF0B-19 stops on unmount (timer cleanup)", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    const backend = signedInBackend().on(`GET /courses/${COURSE_ID}`, () => json(200, course())).on(DOCS, () => json(200, page([doc({ status: "queued" })], 100)));
    const view = workspace();
    await within(await screen.findByRole("region", { name: "Materials" })).findByText("Extracting");
    const initial = backend.count(DOCS);
    view.unmount();
    await tick();
    await tick();
    expect(backend.count(DOCS)).toBe(initial);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("GF0B-19 backs off on errors, stops after repeated failures and offers Try again", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    let healthy = true;
    const busy = doc({ status: "indexing", ready_at: null });
    const backend = signedInBackend()
      .on(`GET /courses/${COURSE_ID}`, () => json(200, course()))
      .on(DOCS, () => (healthy ? json(200, page([busy], 100)) : problem(503, "")));
    workspace();
    await within(await screen.findByRole("region", { name: "Materials" })).findByText("Extracting");
    healthy = false;
    for (let failure = 0; failure < MAX_POLL_FAILURES; failure += 1) {
      const before = backend.count(DOCS);
      await tick(30_000);
      await waitFor(() => expect(backend.count(DOCS)).toBeGreaterThan(before)); // a poll ran (its retries use real timeouts)
      await act(async () => new Promise((r) => setTimeout(r, 50)));
    }
    expect(await screen.findByText("Status updates stopped.")).toBeVisible();
    const stoppedAt = backend.count(DOCS);
    await tick(30_000);
    expect(backend.count(DOCS)).toBe(stoppedAt);
    healthy = true;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.queryByText("Status updates stopped.")).toBeNull());
  });
});

describe("GF0B-24 session expiry during a protected operation", () => {
  it("GF0B-24 a retry answered 401 with a failed refresh ends the session and returns to sign-in", async () => {
    const failed = doc({ file_name: "notes.pdf", status: "failed", error_code: "timed_out" });
    let refreshOk = true;
    const backend = signedInBackend()
      .on("POST /auth/refresh", () => (refreshOk ? json(200, { access_token: "t", token_type: "bearer", expires_in: 900 }) : problem(401, "session_invalid")))
      .on(`GET /courses/${COURSE_ID}`, () => json(200, course()))
      .on(DOCS, () => json(200, page([failed], 100)))
      .on(`POST /documents/${failed.id}/retry`, () => problem(401, "token_invalid"));
    workspace();
    const retry = await screen.findByRole("button", { name: "Retry notes.pdf" });
    refreshOk = false;
    await userEvent.click(retry);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith(`/signin?next=${encodeURIComponent(`/courses/${COURSE_ID}`)}`));
    expect(backend.count(`POST /documents/${failed.id}/retry`)).toBe(1);
    expect(tokenStore.get()).toBeNull();
  });
});

describe("GF0B-15 GF0B-16 GF0B-17 upload flow", () => {
  it("GF0B-15 uploads one file per request, one at a time, with per-file progress and independent outcomes", async () => {
    installFakeXHR();
    signedInBackend().on(`GET /courses/${COURSE_ID}`, () => json(200, course())).on(DOCS, () => json(200, page([], 100)));
    const { container } = upload();
    expect(await screen.findByRole("heading", { level: 1, name: "Add materials" })).toBeVisible();
    const input = container.querySelector<HTMLInputElement>("input[type=file]")!;
    await user().upload(input, [pdf("a.pdf"), pdf("b.pdf"), new File(["PK\u0003\u0004x"], "c.pptx")]);
    await addFiles();
    await waitFor(() => expect(FakeXHR.all).toHaveLength(1));
    expect(xhrFor("a.pdf")).toBeDefined();
    expect(screen.getAllByText("Waiting")).toHaveLength(2);

    act(() => xhrFor("a.pdf")!.progress(500, 1000));
    expect(await screen.findByText("Uploading 50%")).toBeVisible();
    expect(screen.getByRole("progressbar", { name: "Uploading a.pdf" })).toHaveAttribute("aria-valuenow", "50");
    expect(FakeXHR.all).toHaveLength(1); // still one transfer at a time

    const accepted = doc({ file_name: "a.pdf", status: "queued", ready_at: null, page_count: null });
    act(() => xhrFor("a.pdf")!.respond(202, { documents: [{ ...accepted, duplicate: false }] }));
    expect(await screen.findByTestId("upload-announcer")).toHaveTextContent("a.pdf uploaded. Processing started.");
    await waitFor(() => expect(xhrFor("b.pdf")).toBeDefined());
    act(() => xhrFor("b.pdf")!.respond(422, { type: "about:blank#upload_rejected", files: [{ file: "b.pdf", reason: "type_mismatch", message: "x" }] }));
    await waitFor(() => expect(xhrFor("c.pptx")).toBeDefined());
    act(() => xhrFor("c.pptx")!.respond(202, { documents: [{ ...doc({ file_name: "c.pptx", status: "queued" }), duplicate: false }] }));

    const rows = await screen.findAllByRole("listitem");
    await waitFor(() => expect(screen.getAllByText("Extracting", { selector: "span" })).toHaveLength(2));
    expect(screen.getByText("The file's content does not match its extension.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Remove b.pdf" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Retry b.pdf" })).toBeNull();
    expect(rows.length).toBeGreaterThanOrEqual(3);
    expect(FakeXHR.all).toHaveLength(3);
  });

  it("GF0B-14 files refused on the client never start a request; the same file chosen twice is queued once", async () => {
    installFakeXHR();
    signedInBackend().on(`GET /courses/${COURSE_ID}`, () => json(200, course())).on(DOCS, () => json(200, page([doc({ status: "queued" }), doc({ status: "queued" }), doc({ status: "queued" }), doc({ status: "queued" }), doc({ status: "queued" })], 100)));
    const { container } = upload();
    await screen.findByText("5 files");
    const input = container.querySelector<HTMLInputElement>("input[type=file]")!;
    const same = pdf("same.pdf", 77);
    await user().upload(input, [new File(["x"], "notes.txt"), new File([], "empty.pdf"), same]);
    await user().upload(input, [pdf("same.pdf", 77)]);
    expect(await screen.findByText("This file type isn’t supported. Upload PDF, Word (.docx) or PowerPoint (.pptx).")).toBeVisible();
    expect(screen.getByText("The file is empty.")).toBeVisible();
    expect(screen.getAllByText("same.pdf")).toHaveLength(1);
    expect(FakeXHR.all).toHaveLength(0);
  });

  it("GF0B-16 waits while 5 documents are processing and starts when the poll shows capacity", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    installFakeXHR();
    let busy = Array.from({ length: 5 }, () => doc({ status: "embedding", ready_at: null }));
    signedInBackend().on(`GET /courses/${COURSE_ID}`, () => json(200, course())).on(DOCS, () => json(200, page(busy, 100)));
    const { container } = upload();
    await screen.findByText("5 files");
    await user().upload(container.querySelector<HTMLInputElement>("input[type=file]")!, [pdf("next.pdf")]);
    await addFiles();
    expect(await screen.findByText("Waiting for other files to finish processing…")).toBeVisible();
    expect(FakeXHR.all).toHaveLength(0);
    busy = [{ ...busy[0]!, status: "ready" }, ...busy.slice(1)];
    await tick();
    // the content check (file signature) reads the file asynchronously before the transfer starts
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
    });
    expect(FakeXHR.all).toHaveLength(1);
  });

  it("GF0B-16 queue_full requeues the row while this course has work in progress, otherwise offers Retry", async () => {
    installFakeXHR();
    signedInBackend().on(`GET /courses/${COURSE_ID}`, () => json(200, course())).on(DOCS, () => json(200, page([], 100)));
    const { container } = upload();
    await screen.findByText("0 files");
    await user().upload(container.querySelector<HTMLInputElement>("input[type=file]")!, [pdf("full.pdf")]);
    await addFiles();
    await waitFor(() => expect(FakeXHR.all).toHaveLength(1));
    act(() => FakeXHR.all[0]!.respond(429, { type: "about:blank#queue_full" }));
    expect(await screen.findByText("Too many documents are still processing. Try again later.")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Retry full.pdf" }));
    await waitFor(() => expect(FakeXHR.all).toHaveLength(2));
  });

  it("GF0B-16 Cancel aborts the transfer and removes the row; a network failure offers Retry", async () => {
    installFakeXHR();
    signedInBackend().on(`GET /courses/${COURSE_ID}`, () => json(200, course())).on(DOCS, () => json(200, page([], 100)));
    const { container } = upload();
    await screen.findByText("0 files");
    const input = container.querySelector<HTMLInputElement>("input[type=file]")!;
    await user().upload(input, [pdf("big.pdf")]);
    await addFiles();
    await waitFor(() => expect(FakeXHR.all).toHaveLength(1));
    await userEvent.click(screen.getByRole("button", { name: "Cancel upload of big.pdf" }));
    expect(FakeXHR.all[0]!.aborted).toBe(true);
    await waitFor(() => expect(screen.queryByText("big.pdf")).toBeNull());

    await user().upload(input, [pdf("flaky.pdf")]);
    await addFiles();
    await waitFor(() => expect(FakeXHR.all).toHaveLength(2));
    act(() => FakeXHR.all[1]!.fail());
    expect(await screen.findByText("Upload failed. Check your connection and try again.")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Retry flaky.pdf" }));
    await waitFor(() => expect(FakeXHR.all).toHaveLength(3));
  });

  it("GF0B-16 a rate limit pauses new transfers and tells the user when to retry", async () => {
    installFakeXHR();
    signedInBackend().on(`GET /courses/${COURSE_ID}`, () => json(200, course())).on(DOCS, () => json(200, page([], 100)));
    const { container } = upload();
    await screen.findByText("0 files");
    await user().upload(container.querySelector<HTMLInputElement>("input[type=file]")!, [pdf("1.pdf"), pdf("2.pdf")]);
    await addFiles();
    await waitFor(() => expect(FakeXHR.all).toHaveLength(1));
    act(() => FakeXHR.all[0]!.respond(429, { type: "about:blank#rate_limited" }, { "Retry-After": "600" }));
    expect(await screen.findByText("Too many uploads in the last hour. Try again in 10 minutes.")).toBeVisible();
    await act(async () => new Promise((r) => setTimeout(r, 50)));
    expect(FakeXHR.all).toHaveLength(1);
    expect(screen.getByText("Waiting to upload…")).toBeVisible();
  });

  it("GF0B-17 a duplicate is reported, and server rejections stay on their own row", async () => {
    installFakeXHR();
    const existing = doc({ file_name: "same.pdf" });
    signedInBackend().on(`GET /courses/${COURSE_ID}`, () => json(200, course())).on(DOCS, () => json(200, page([existing], 100)));
    const { container } = upload();
    await screen.findByText("1 file");
    await user().upload(container.querySelector<HTMLInputElement>("input[type=file]")!, [pdf("same-copy.pdf"), pdf("huge.pdf")]);
    await addFiles();
    await waitFor(() => expect(FakeXHR.all).toHaveLength(1));
    act(() => FakeXHR.all[0]!.respond(202, { documents: [{ ...existing, duplicate: true }] }));
    expect(await screen.findByText("“same.pdf” is already in this course.")).toBeVisible();
    await waitFor(() => expect(FakeXHR.all).toHaveLength(2));
    act(() => FakeXHR.all[1]!.respond(413, { type: "about:blank#quota_exceeded" }));
    expect(await screen.findByText("Your storage quota is full. Delete documents to upload more.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Remove huge.pdf" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Retry huge.pdf" })).toBeNull();
  });

  it("GF0B-21 Empty and Not supported server rows offer Remove (delete with confirmation); Indexed rows offer Open", async () => {
    const empty = doc({ file_name: "blank.pdf", status: "failed", error_code: "no_text" });
    const ready = doc({ file_name: "ok.pdf" });
    let stored = [empty, ready];
    signedInBackend()
      .on(`GET /courses/${COURSE_ID}`, () => json(200, course()))
      .on(DOCS, () => json(200, page(stored, 100)))
      .on(`DELETE /documents/${empty.id}`, () => {
        stored = [ready];
        return new Response(null, { status: 204 });
      });
    upload();
    expect(await screen.findByText("This file has no readable text, so there is nothing to index.")).toBeVisible();
    expect(screen.getByRole("link", { name: "Open ok.pdf" })).toHaveAttribute("href", `/courses/${COURSE_ID}/documents/${ready.id}/summary`);
    await userEvent.click(screen.getByRole("button", { name: "Remove blank.pdf" }));
    await userEvent.click(within(screen.getByRole("dialog", { name: "Delete this file?" })).getByRole("button", { name: "Delete file" }));
    await waitFor(() => expect(screen.queryByText("blank.pdf")).toBeNull());
  });

  it("GF0B-27 the dropzone's keyboard path is the Choose files button, and drops are accepted", async () => {
    installFakeXHR();
    signedInBackend().on(`GET /courses/${COURSE_ID}`, () => json(200, course())).on(DOCS, () => json(200, page([], 100)));
    const { container } = upload();
    const choose = await screen.findByRole("button", { name: "Choose files" });
    const input = container.querySelector<HTMLInputElement>("input[type=file]")!;
    expect(input).toHaveAttribute("hidden");
    const opened = vi.spyOn(input, "click");
    choose.focus();
    await userEvent.keyboard("{Enter}");
    expect(opened).toHaveBeenCalled();
    const zone = screen.getByTestId("dropzone");
    const drop = new Event("drop", { bubbles: true }) as Event & { dataTransfer: { files: File[] } };
    Object.assign(drop, { dataTransfer: { files: [pdf("dropped.pdf")] } });
    act(() => zone.dispatchEvent(drop));
    await addFiles();
    await waitFor(() => expect(xhrFor("dropped.pdf")).toBeDefined());
  });
});

describe("GF0B-25 F-M4-03 — Frontend Rendering Safety in the workspace and upload list", () => {
  it("GF0B-25 hostile course and file names render as text with no markup and no javascript: links", async () => {
    const docs = HOSTILE.map((name) => doc({ file_name: name }));
    signedInBackend()
      .on(`GET /courses/${COURSE_ID}`, () => json(200, course({ name: HOSTILE[0], description: HOSTILE[1] })))
      .on(DOCS, () => json(200, page(docs, 100)));
    const view = workspace();
    expect(await screen.findByRole("heading", { level: 1, name: HOSTILE[0] })).toBeVisible();
    for (const name of HOSTILE) expect((await screen.findAllByText(name)).length).toBeGreaterThan(0);
    const check = () => {
      expect(document.querySelector("main script, main img:not([src=\"/brand/intellistudy-logo.svg\"]), main iframe")).toBeNull();
      expect([...document.querySelectorAll("a")].map((a) => a.getAttribute("href") ?? "").filter((h) => !h.startsWith("/") && h !== "#main")).toEqual([]);
    };
    check();
    view.unmount();
    upload();
    for (const name of HOSTILE) expect((await screen.findAllByText(name)).length).toBeGreaterThan(0);
    check();
  });
});
