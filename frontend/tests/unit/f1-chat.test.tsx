import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChatPage } from "@/features/chat/components/ChatPage";
import type { ConversationDetail, ConversationOut, MessageOut } from "@/lib/api/types";
import { tokenStore } from "@/lib/auth/token-store";
import { deferred, renderPage, signedInBackend } from "../helpers/app";
import { COURSE_ID, OTHER_ID, course, doc, page } from "../helpers/data";
import { HOSTILE_AI, message } from "../helpers/f1-data";
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

const C1 = "66666666-6666-4666-8666-000000000001";
const C2 = "66666666-6666-4666-8666-000000000002";
const LIST = `GET /courses/${COURSE_ID}/conversations`;
const conversation = (id: string, title = "New conversation"): ConversationOut => ({ id, course_id: COURSE_ID, title, created_at: "2026-11-26T09:00:00Z", updated_at: "2026-11-26T09:30:00Z" });
const detail = (id: string, messages: MessageOut[] = []): ConversationDetail => ({ ...conversation(id), messages });

function backend(conversations: ConversationOut[] = []) {
  return signedInBackend()
    .on(`GET /courses/${COURSE_ID}`, () => json(200, course()))
    .on(`GET /courses/${COURSE_ID}/documents`, () => json(200, page([doc(), doc(), doc({ status: "embedding" })], 100)))
    .on(LIST, () => json(200, page(conversations)));
}

function open(search = "") {
  const view = renderPage(<ChatPage courseId={COURSE_ID} />, { shell: "rail", path: `/courses/${COURSE_ID}/chat`, search });
  nav.live = true;
  return view;
}

const composer = () => screen.findByLabelText("Ask a question about your materials");

beforeEach(() => tokenStore.clear());

describe("GF1-11 conversations", () => {
  it("GF1-11 with none: the empty state creates one (no invented title) and selects it", async () => {
    const created = conversation(C1);
    const b = backend().on(`POST /courses/${COURSE_ID}/conversations`, () => json(201, created)).on(`GET /conversations/${C1}`, () => json(200, detail(C1)));
    open();
    expect(await screen.findByRole("heading", { name: "No conversations yet" })).toBeVisible();
    await userEvent.click(screen.getAllByRole("button", { name: "New conversation" })[1]!);
    await waitFor(() => expect(nav.search.get("c")).toBe(C1));
    expect(b.calls.find((c) => c.method === "POST" && c.path.endsWith("/conversations"))!.body).toEqual({});
    expect(await screen.findByText("Ask your first question below.")).toBeVisible();
    expect(screen.getByText("Searching all 2 files in this course")).toBeVisible(); // ready files only
  });

  it("GF1-11 without ?c the most recently active conversation opens; the list pages by 50 with Show more", async () => {
    const first = Array.from({ length: 50 }, (_, i) => conversation(`77777777-7777-4777-8777-${String(i).padStart(12, "0")}`, `Chat ${i}`));
    const b = signedInBackend()
      .on(`GET /courses/${COURSE_ID}`, () => json(200, course()))
      .on(`GET /courses/${COURSE_ID}/documents`, () => json(200, page([], 100)))
      .on(LIST, (url) => json(200, url.searchParams.get("offset") === "50" ? page([conversation(C2, "Chat 50")], 50, 50) : page(first)))
      .match(/^GET \/conversations\//, (url) => json(200, detail(url.pathname.split("/").pop()!)));
    open();
    await waitFor(() => expect(nav.search.get("c")).toBe(first[0]!.id));
    expect(nav.replace).toHaveBeenCalled(); // replace, not push: no extra history entry
    await userEvent.click(await screen.findByRole("button", { name: "Show more conversations" }));
    expect(await screen.findByRole("link", { name: /Chat 50/ })).toBeVisible();
    expect(b.calls.filter((c) => c.path.endsWith("/conversations")).map((c) => c.search)).toContain("?limit=50&offset=50");
  });

  it("GF1-11 delete asks first (focus on Cancel), then opens the neighbour", async () => {
    let list = [conversation(C1, "First"), conversation(C2, "Second")];
    const b = backend()
      .on(LIST, () => json(200, page(list)))
      .match(/^GET \/conversations\//, (url) => json(200, detail(url.pathname.split("/").pop()!)))
      .on(`DELETE /conversations/${C1}`, () => {
        list = [list[1]!];
        return new Response(null, { status: 204 });
      });
    open(`c=${C1}`);
    await userEvent.click(await screen.findByRole("button", { name: "Delete conversation" }));
    const dialog = screen.getByRole("dialog", { name: "Delete this conversation?" });
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    expect(b.count(`DELETE /conversations/${C1}`)).toBe(0);
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete conversation" }));
    await waitFor(() => expect(nav.search.get("c")).toBe(C2));
    expect(await screen.findByText("Conversation deleted.")).toBeVisible();
    await waitFor(() => expect(screen.queryByRole("link", { name: /First/ })).toBeNull());
  });
});

describe("GF1-12 GF1-14 history and states", () => {
  it("GF1-12 GF1-14 loads every exchange in order and renders each real state distinctly", async () => {
    const messages = [
      message({ id: "a", question: "Q answered", state: "answered" }),
      message({ id: "b", question: "Q partial", state: "partial", missing_terms: ["zymurgy"] }),
      message({ id: "c", question: "Q low", state: "low_confidence" }),
      message({ id: "d", question: "Q refused", state: "refused", refusal_reason: "not_relevant", text: "I couldn't find this.", citations: [], nearest: [] }),
      message({ id: "e", question: "Q outage", state: "refused", refusal_reason: "llm_unavailable", text: "The answer service is temporarily unavailable.", citations: [], nearest: [] }),
    ];
    backend([conversation(C1)]).on(`GET /conversations/${C1}`, () => json(200, detail(C1, messages)));
    open(`c=${C1}`);
    const log = await screen.findByRole("log", { name: "Messages" });
    await within(log).findByText("Q outage");
    expect([...log.querySelectorAll("[data-state]")].map((el) => el.getAttribute("data-state"))).toEqual(["answered", "partial", "low_confidence", "refused", "refused"]);
    expect(within(log).getAllByText("Answered from 1 file", { selector: "span" })).toHaveLength(2); // answered + low confidence
    expect(within(log).getByText("Partly answered from 1 file")).toBeVisible();
    expect(within(log).getByText("Low confidence")).toBeVisible();
    expect(within(log).getByText("I couldn’t find this in your materials")).toBeVisible();
    expect(within(log).getByText("The answering service is unavailable")).toBeVisible();
    expect(screen.getByText("Answers come only from your uploaded files. Check the cited page before relying on them.")).toBeVisible();
  });

  it("GF1-15 a source opens for its own message only; switching conversations clears it", async () => {
    const one = message({ id: "a", text: "First answer [1].", citations: [{ ...message().citations[0]!, passage: "Passage of A." }] });
    const two = message({ id: "b", text: "Second answer [1].", citations: [{ ...message().citations[0]!, file_name: "other.pdf", passage: "Passage of B." }] });
    backend([conversation(C1), conversation(C2)])
      .on(`GET /conversations/${C1}`, () => json(200, detail(C1, [one, two])))
      .on(`GET /conversations/${C2}`, () => json(200, detail(C2, [message({ id: "z", text: "Other conversation." })])));
    open(`c=${C1}`);
    await screen.findByText("Second answer", { exact: false });
    await userEvent.click(screen.getAllByRole("button", { name: "Source 1: other.pdf, p. 3" })[0]!);
    const panel = screen.getByRole("complementary", { name: "Source" });
    expect(within(panel).getByText("Passage of B.")).toBeVisible();
    expect(within(panel).queryByText("Passage of A.")).toBeNull();
    expect(within(panel).getByText("Wider text.")).toBeVisible(); // SURROUNDING TEXT from `context`
    const firstBadges = screen.getAllByRole("button", { name: "Source 1: notes.pdf, p. 3" });
    expect(firstBadges.every((b) => b.getAttribute("aria-pressed") === "false")).toBe(true);
    expect(screen.getAllByRole("link", { name: /New conversation/ }).map((a) => a.getAttribute("href"))).toContain(`/courses/${COURSE_ID}/chat?c=${C2}`);
    act(() => nav.push(`/courses/${COURSE_ID}/chat?c=${C2}`)); // what the conversation link does in the app
    await screen.findByText("Other conversation.");
    expect(screen.queryByRole("complementary", { name: "Source" })).toBeNull();
    expect(screen.queryByText("Passage of B.")).toBeNull();
  });
});

describe("GF1-13 GF1-16 sending", () => {
  it("GF1-13 sends once, shows the pending exchange without invented content, appends the server's exchange and clears the box", async () => {
    const hold = deferred<void>();
    const stored = message({ id: "srv-1", question: "What is Little's Law?", text: "Little's Law [1]." });
    const b = backend([conversation(C1)])
      .on(`GET /conversations/${C1}`, () => json(200, detail(C1)))
      .on(`POST /conversations/${C1}/messages`, () => hold.promise.then(() => json(201, stored)));
    open(`c=${C1}`);
    const box = await composer();
    await userEvent.type(box, "  What is Little's Law?  ");
    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard("{Enter}");
    await userEvent.click(screen.getByRole("button", { name: "Answering…" }));
    expect(b.count(`POST /conversations/${C1}/messages`)).toBe(1);
    const log = screen.getByRole("log", { name: "Messages" });
    expect(within(log).getByText("Working")).toBeVisible();
    expect(within(log).getByText("Searching 2 files…")).toBeVisible();
    expect(log.querySelector("[data-state]")).toBeNull(); // no answer before the server's
    expect(box).toHaveValue("  What is Little's Law?  ");
    hold.resolve();
    expect(await within(log).findByText("Answered from 1 file", { selector: "span" })).toBeVisible();
    expect(box).toHaveValue("");
    expect(log.querySelector('[data-message="srv-1"]')).not.toBeNull();
  });

  it("GF1-16 a failure keeps the text, shows fixed copy and is never retried; a rate limit blocks Send until Retry-After", async () => {
    let reply: () => Response = () => {
      throw new TypeError("Failed to fetch");
    };
    const b = backend([conversation(C1)]).on(`GET /conversations/${C1}`, () => json(200, detail(C1))).on(`POST /conversations/${C1}/messages`, () => reply());
    open(`c=${C1}`);
    const box = await composer();
    await userEvent.type(box, "Keep me");
    await userEvent.keyboard("{Enter}");
    expect(await screen.findByText(/Your question is kept/)).toBeVisible();
    expect(box).toHaveValue("Keep me");
    expect(b.count(`POST /conversations/${C1}/messages`)).toBe(1);
    reply = () => problem(429, "rate_limited", "Too many requests.", { "Retry-After": "30" });
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("You’ve asked many questions in the last minute. Try again in 30 seconds.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    expect(screen.getByLabelText("Ask a question about your materials")).toHaveAttribute("aria-invalid", "true");
  });

  it("GF1-13 empty and too-long questions are refused on the client without a request", async () => {
    const b = backend([conversation(C1)]).on(`GET /conversations/${C1}`, () => json(200, detail(C1)));
    open(`c=${C1}`);
    const box = await composer();
    await userEvent.type(box, "   ");
    await userEvent.keyboard("{Enter}");
    expect(await screen.findByText("Type a question first.")).toBeVisible();
    await userEvent.clear(box);
    await userEvent.click(box);
    await userEvent.paste("a".repeat(2001));
    await userEvent.keyboard("{Enter}");
    expect(await screen.findByText("Use 2000 characters or fewer.")).toBeVisible();
    expect(b.count(`POST /conversations/${C1}/messages`)).toBe(0);
  });

  it("GF1-16 session expiry while sending returns to sign-in and keeps nothing", async () => {
    let refreshOk = true;
    backend([conversation(C1)])
      .on("POST /auth/refresh", () => (refreshOk ? json(200, { access_token: "t", token_type: "bearer", expires_in: 900 }) : problem(401, "session_invalid")))
      .on(`GET /conversations/${C1}`, () => json(200, detail(C1)))
      .on(`POST /conversations/${C1}/messages`, () => problem(401, "token_invalid"));
    open(`c=${C1}`);
    nav.live = false; // the router mock records the redirect; the real app then unmounts the protected page
    const box = await composer();
    refreshOk = false;
    await userEvent.type(box, "Hello there");
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith(expect.stringMatching(/^\/signin\?next=/)));
    expect(tokenStore.get()).toBeNull();
  });
});

describe("GF1-17 not found without leaks", () => {
  it("GF1-17 foreign, missing, malformed and other-course conversation ids show the same not-found state", async () => {
    const texts: string[] = [];
    for (const [search, reply] of [
      [`c=${C1}`, () => problem(404, "not_found", "Resource not found.")],
      [`c=${C2}`, () => json(200, { ...detail(C2, [message({ question: "Secret question" })]), course_id: OTHER_ID, title: "Secret title" })],
      ["c=../../etc/passwd", () => json(200, {})],
    ] as const) {
      const b = backend().match(/^GET \/conversations\//, reply);
      const view = open(search);
      expect(await screen.findByRole("heading", { level: 1, name: "Not found" })).toBeVisible();
      texts.push(screen.getByRole("heading", { level: 1, name: "Not found" }).parentElement!.textContent ?? "");
      expect(document.body.textContent).not.toMatch(/Secret/);
      if (search.includes("etc")) expect(b.calls.filter((c) => c.path.startsWith("/conversations/"))).toEqual([]);
      view.unmount();
    }
    expect(new Set(texts).size).toBe(1);
  });
});

describe("GF1-19 cache isolation", () => {
  it("GF1-19 signing out clears every F1 query (summaries, conversations, histories)", async () => {
    const b = backend([conversation(C1)]).on(`GET /conversations/${C1}`, () => json(200, detail(C1, [message()]))).on("POST /auth/logout", () => new Response(null, { status: 204 }));
    const { queryClient } = open(`c=${C1}`);
    await screen.findByText("Answered from 1 file", { selector: "span" });
    queryClient.setQueryData(["summary", "d-1"], { secret: true });
    expect(queryClient.getQueryData(["conversation", C1])).toBeTruthy();
    nav.live = false; // the router mock records the redirect; the real app then unmounts the protected page
    await userEvent.click(screen.getAllByRole("button", { name: /^Account: Test Student/ })[0]!);
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(b.count("POST /auth/logout")).toBe(1));
    await waitFor(() => expect(queryClient.getQueryCache().getAll().filter((q) => ["summary", "conversation", "conversations"].includes(String(q.queryKey[0])) && q.state.data !== undefined)).toEqual([]));
  });
});

describe("GF1-20 GF1-21 F-M4-03 — Frontend Rendering Safety / F-M3-03 — Prompt Injection Residual in chat", () => {
  it("GF1-21 injected answers, questions, titles and sources stay text and cause no request, navigation or deletion", async () => {
    const hostile = HOSTILE_AI.join(" ");
    const b = backend([conversation(C1, HOSTILE_AI[2])]).on(`GET /conversations/${C1}`, () =>
      json(200, { ...detail(C1, [message({ question: hostile, text: `${hostile} [1]`, citations: [{ ...message().citations[0]!, passage: hostile, context: hostile, file_name: HOSTILE_AI[1] }], missing_terms: [...HOSTILE_AI] })]), title: HOSTILE_AI[2] }),
    );
    open(`c=${C1}`);
    const log = await screen.findByRole("log", { name: "Messages" });
    await within(log).findAllByText(/Ignore all previous instructions/);
    await userEvent.click(screen.getAllByRole("button", { name: /^Source 1:/ })[0]!);
    const main = screen.getByRole("main");
    expect(main.querySelector("script, img, iframe")).toBeNull();
    expect([...document.querySelectorAll("a")].map((a) => a.getAttribute("href") ?? "").filter((h) => !h.startsWith("/") && h !== "#main")).toEqual([]);
    expect(b.calls.filter((c) => c.method === "DELETE" || (c.method === "POST" && !c.path.startsWith("/auth/")))).toEqual([]);
    expect(nav.push.mock.calls.concat(nav.replace.mock.calls).every(([href]) => String(href).startsWith(`/courses/${COURSE_ID}/chat`))).toBe(true);
  });
});
