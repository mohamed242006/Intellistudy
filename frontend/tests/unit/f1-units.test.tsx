import { readFileSync } from "node:fs";
import { join } from "node:path";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { ChatComposer } from "@/design-system/components/ChatComposer";
import { CitationBadge } from "@/design-system/components/CitationBadge";
import { SourceCard } from "@/design-system/components/SourceCard";
import { CitationText } from "@/design-system/compositions/CitationText";
import { SummarySection } from "@/design-system/compositions/SummarySection";
import { AssistantMessage, answerKind } from "@/features/chat/components/ChatMessage";
import { neighbourAfterDelete, parseConversationParam, questionProblem, sendErrorMessage } from "@/features/chat/components/ChatPage";
import { BACKEND_NOTICES } from "@/features/chat/strings";
import { MAX_POLL_FAILURES } from "@/features/documents/polling";
import { SourceView, type SourceItem } from "@/features/sources/SourceView";
import { parseSourceParam } from "@/features/summary/components/SummaryPage";
import { summaryPollDelay } from "@/features/summary/hooks";
import { generationFailure, summaryRequestError } from "@/features/summary/messages";
import { ApiError, apiErrorFromBody } from "@/lib/api/errors";
import type { SummaryOut } from "@/lib/api/types";
import { parseCitations, splitStatements } from "@/lib/citations/parse";
import { queryKeys } from "@/lib/query/keys";
import { HOSTILE_AI, message } from "../helpers/f1-data";
import { sourceFiles } from "./static/scan";

const REPO = join(process.cwd(), "..");
const known = (...n: number[]) => new Set(n);

describe("GF1-07 citation parsing", () => {
  it("GF1-07 turns only known [n] and [n, m] markers into citations and keeps all other text exactly", () => {
    expect(parseCitations("A [1]. B [1, 2].", known(1, 2))).toEqual([
      { kind: "text", text: "A " },
      { kind: "cite", number: 1 },
      { kind: "text", text: ". B " },
      { kind: "cite", number: 1 },
      { kind: "cite", number: 2 },
      { kind: "text", text: "." },
    ]);
    expect(parseCitations("[1][2] start and end [12]", known(1, 2, 12)).map((s) => (s.kind === "cite" ? s.number : s.text))).toEqual([1, 2, " start and end ", 12]);
    expect(parseCitations("x [3] y", known(1))).toEqual([{ kind: "text", text: "x [3] y" }]); // unknown: no guessed source
    expect(parseCitations("x [1, 9] y", known(1))).toEqual([{ kind: "text", text: "x [1, 9] y" }]); // never a partial group
    for (const malformed of ["[ 1]", "[1,]", "[a]", "[]", "[1.5]", "[-1]", "[[1]", "[1"]) {
      expect(parseCitations(malformed, known(1)).filter((s) => s.kind === "cite").length, malformed).toBeLessThanOrEqual(1);
      expect(parseCitations(malformed, known(1)).map((s) => (s.kind === "text" ? s.text : `[${s.number}]`)).join("")).toBe(malformed);
    }
  });

  it("GF1-07 keeps Unicode, right-to-left and hostile text around markers verbatim", () => {
    for (const text of ["مرحبا [1] שלום", "‮evil‬ [1]", "[1]<script>alert(1)</script>", "😀".repeat(3) + "[1]"]) {
      const out = parseCitations(text, known(1));
      expect(out.map((s) => (s.kind === "text" ? s.text : `[${s.number}]`)).join("")).toBe(text);
    }
  });

  it("GF1-06 splits a summary section into statements only after a marker and its full stop", () => {
    expect(splitStatements("One sentence [1]. Two, with e.g. dots [1, 2]. Three [3]!")).toEqual(["One sentence [1].", "Two, with e.g. dots [1, 2].", "Three [3]!"]);
    expect(splitStatements("No markers. Still one statement.")).toEqual(["No markers. Still one statement."]);
  });
});

describe("GF1-08 CitationBadge", () => {
  it("GF1-08 is a named button with a 44×44 hit area, pressed state and keyboard activation", async () => {
    const onSelect = vi.fn();
    render(<CitationBadge number={12} label="Source 12: notes.pdf, p. 3" active={false} onSelect={onSelect} />);
    const badge = screen.getByRole("button", { name: "Source 12: notes.pdf, p. 3" });
    expect(badge).toHaveTextContent("[12]");
    expect(badge).toHaveAttribute("aria-pressed", "false");
    expect(badge.className).toContain("before:size-11"); // 44 × 44 transparent hit area
    badge.focus();
    await userEvent.keyboard("{Enter}");
    expect(onSelect).toHaveBeenCalledWith(badge);
  });

  it("GF1-08 CitationText opens the badge's own number, also for repeated markers", async () => {
    const onSelect = vi.fn();
    render(<CitationText text="a [1] b [2] c [1]." labels={new Map([[1, "Source 1"], [2, "Source 2"]])} activeNumber={2} onSelect={onSelect} />);
    const ones = screen.getAllByRole("button", { name: "Source 1" });
    expect(ones).toHaveLength(2);
    await userEvent.click(ones[1]!);
    expect(onSelect.mock.calls[0]![0]).toBe(1);
    expect(screen.getByRole("button", { name: "Source 2" })).toHaveAttribute("aria-pressed", "true");
  });
});

function ViewHarness({ sources, initial = null }: { sources: SourceItem[]; initial?: number | null }) {
  const [selected, setSelected] = useState<number | null>(initial);
  let last: HTMLElement | null = null;
  return (
    <div>
      <button onClick={(e) => { last = e.currentTarget; setSelected(1); }}>open 1</button>
      <SourceView sources={sources} selected={selected} listTitle="ALL SOURCES IN THIS SUMMARY" showContext onSelect={(n) => setSelected(n)} onClose={() => setSelected(null)} returnFocus={() => last ?? document.querySelector("button")} alwaysShowPanel />
    </div>
  );
}

const SOURCES: SourceItem[] = [
  { number: 1, file_name: "notes.pdf", citation_label: "p. 3", passage: "Line one\nline two " + "x".repeat(400), context: "Around it." },
  { number: 2, file_name: "slides.pptx", citation_label: "slide 4", passage: "Second." },
];

describe("GF1-09 source panel", () => {
  it("GF1-09 desktop: non-modal panel with passage, surrounding text and the list; Escape closes and focus returns", async () => {
    render(<ViewHarness sources={SOURCES} />);
    const panel = screen.getByRole("complementary", { name: "Source" });
    expect(within(panel).getByText("Select a citation badge to see the exact passage.")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "open 1" }));
    expect(within(panel).getByRole("heading", { name: "Source [1]" })).toBeVisible();
    expect(within(panel).getByText(/Line one/)).toHaveClass("whitespace-pre-line");
    expect(within(panel).getByText("Around it.")).toBeVisible();
    expect(screen.queryByRole("dialog")).toBeNull(); // not modal on desktop: nothing is trapped or inert
    expect(document.querySelector("[inert]")).toBeNull();
    within(panel).getByRole("heading", { name: "Source [1]" }).focus();
    await userEvent.keyboard("{Escape}");
    expect(within(panel).queryByRole("heading", { name: "Source [1]" })).toBeNull();
    await vi.waitFor(() => expect(screen.getByRole("button", { name: "open 1" })).toHaveFocus());
  });

  it("GF1-09 one source at a time; an unknown number shows 'unavailable', never another source", async () => {
    render(<ViewHarness sources={SOURCES} initial={7} />);
    expect(screen.getByText("This source isn’t available.")).toBeVisible();
    expect(screen.queryByText("Second.")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /slides\.pptx · slide 4/ }));
    expect(screen.getByRole("heading", { name: "Source [2]" })).toBeVisible();
    expect(screen.getAllByText("Second.")).toHaveLength(1);
  });

  it("GF1-10 narrow screens: the source is a modal bottom sheet (dialog, focus inside, Escape closes)", async () => {
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: false, media: query, addEventListener: () => {}, removeEventListener: () => {} }));
    render(<ViewHarness sources={SOURCES} />);
    expect(screen.queryByRole("complementary")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "open 1" }));
    const sheet = screen.getByRole("dialog", { name: "Source [1]" });
    expect(sheet).toHaveAttribute("data-variant", "sheet");
    expect(sheet.contains(document.activeElement)).toBe(true);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("GF1-09 the ?source= value must name one of this summary's citations", () => {
    const summary = { citations: [{ number: 1 }, { number: 12 }] } as unknown as SummaryOut;
    expect(parseSourceParam("12", summary)).toBe(12);
    for (const raw of [null, "", "0", "3", "-1", "1.0", "1e1", "javascript:alert(1)", "01", "99999"]) expect(parseSourceParam(raw, summary), String(raw)).toBeNull();
  });
});

describe("GF1-06 SummarySection", () => {
  it("GF1-06 is a disclosure: the heading button toggles aria-expanded and hides the statements", async () => {
    render(<SummarySection heading="Cross-cutting concerns" caption="3 sources · pp. 3–4" statements={["One.", "Two."]} defaultExpanded={false} />);
    const toggle = screen.getByRole("button", { name: /Cross-cutting concerns/ });
    expect(screen.getByRole("heading", { level: 2 })).toContainElement(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("One.")).not.toBeVisible();
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("One.")).toBeVisible();
    expect(screen.getByText("3 sources · pp. 3–4")).toBeVisible();
  });
});

function ComposerHarness({ onSubmit, pending = false, blocked = false }: { onSubmit: (v: string) => void; pending?: boolean; blocked?: boolean }) {
  const [value, setValue] = useState("");
  return (
    <ChatComposer label="Ask a question about your materials" value={value} onChange={setValue} onSubmit={() => onSubmit(value)} pending={pending} blocked={blocked} placeholder="p" loadingPlaceholder="Searching your materials…" sendLabel="Send" pendingLabel="Answering…" scope="Searching all 2 files in this course" error={null} maxLength={4000} />
  );
}

describe("GF1-13 ChatComposer", () => {
  it("GF1-13 Enter sends, Shift+Enter adds a line; it has a label and a named Send button", async () => {
    const onSubmit = vi.fn();
    render(<ComposerHarness onSubmit={onSubmit} />);
    const box = screen.getByLabelText("Ask a question about your materials");
    await userEvent.type(box, "line one{Shift>}{Enter}{/Shift}line two");
    expect(onSubmit).not.toHaveBeenCalled();
    expect(box).toHaveValue("line one\nline two");
    await userEvent.keyboard("{Enter}");
    expect(onSubmit).toHaveBeenCalledWith("line one\nline two");
    expect(screen.getByRole("button", { name: "Send" })).toBeVisible();
  });

  it("GF1-13 while pending: read-only text, 'Answering…' busy button, no second submit; blocked disables Send", async () => {
    const onSubmit = vi.fn();
    const { rerender } = render(<ComposerHarness onSubmit={onSubmit} pending />);
    expect(screen.getByLabelText("Ask a question about your materials")).toHaveAttribute("readonly");
    const button = screen.getByRole("button", { name: "Answering…" });
    expect(button).toHaveAttribute("aria-busy", "true");
    await userEvent.click(button);
    screen.getByLabelText("Ask a question about your materials").focus();
    await userEvent.keyboard("{Enter}");
    expect(onSubmit).not.toHaveBeenCalled();
    rerender(<ComposerHarness onSubmit={onSubmit} blocked />);
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("GF1-13 validates like the backend: whitespace collapsed, 1-2000 characters", () => {
    expect(questionProblem("   \n\t ")).toBe("empty");
    expect(questionProblem("a".repeat(2000))).toBeNull();
    expect(questionProblem(`${"a ".repeat(1000)}   `)).toBeNull(); // 1999 after collapsing
    expect(questionProblem("a".repeat(2001))).toBe("too_long");
    expect(read("backend/app/services/chat.py")).toContain("MAX_QUESTION_CHARS = 2000");
  });
});

function read(path: string) {
  return readFileSync(join(REPO, path), "utf8");
}

describe("GF1-14 GF1-18 answer states", () => {
  const select = vi.fn();
  it("GF1-14 answered: caption from the cited files, text with badges, SOURCES row; no internals shown", () => {
    render(<AssistantMessage message={message()} activeNumber={null} onSelect={select} />);
    expect(screen.getByText("Answered from 1 file")).toBeVisible();
    const named = screen.getAllByRole("button", { name: "Source 1: notes.pdf, p. 3" }); // inline badge + SOURCES row
    expect(named).toHaveLength(2);
    expect(named[0]).toHaveTextContent("[1]");
    expect(screen.getByText("SOURCES")).toBeVisible();
    expect(document.body.textContent).not.toMatch(/some-model-name|secret draft|1\.5/);
  });

  it("GF1-18 partial and low confidence keep their notices; partial is never shown as answered", () => {
    const { unmount } = render(<AssistantMessage message={message({ state: "partial", missing_terms: ["zymurgy", "<b>x</b>"] })} activeNumber={null} onSelect={select} />);
    expect(screen.getByText("Partly answered from 1 file")).toBeVisible();
    expect(screen.queryByText(/^Answered from/)).toBeNull();
    expect(screen.getByText("Only part of your question is covered")).toBeVisible();
    expect(screen.getByText("Not found in your materials: zymurgy, <b>x</b>.")).toBeVisible();
    unmount();
    render(<AssistantMessage message={message({ state: "low_confidence" })} activeNumber={null} onSelect={select} />);
    expect(screen.getByText("Low confidence")).toBeVisible();
    expect(screen.getByText(BACKEND_NOTICES.low_confidence!)).toBeVisible();
  });

  it("GF1-14 refused shows the refusal and the closest material, never citations; llm_unavailable is distinct", () => {
    const nearest = [{ document_id: "d-1", file_name: "notes.pdf", citation_label: "p. 1", page: 1, slide: null, passage: "Closest passage." }];
    const { unmount } = render(<AssistantMessage message={message({ state: "refused", refusal_reason: "not_relevant", text: "I couldn't find this.", citations: [], nearest })} activeNumber={null} onSelect={select} />);
    expect(screen.getByText("Not found in your materials")).toBeVisible();
    expect(screen.getByText("I couldn’t find this in your materials")).toBeVisible();
    expect(screen.getByText("Closest passage.")).toBeVisible();
    expect(screen.queryByRole("button")).toBeNull();
    unmount();
    render(<AssistantMessage message={message({ state: "refused", refusal_reason: "llm_unavailable", text: "The answer service is temporarily unavailable.", citations: [], nearest })} activeNumber={null} onSelect={select} />);
    expect(screen.getByText("The answering service is unavailable")).toBeVisible();
    expect(screen.queryByText("Closest passage.")).toBeNull();
  });

  it("GF1-18 unknown future states claim nothing; states map only to the backend's values", () => {
    expect(["answered", "partial", "low_confidence", "refused", "grounded"].map(answerKind)).toEqual(["answered", "partial", "low_confidence", "refused", "unknown"]);
    render(<AssistantMessage message={message({ state: "grounded" })} activeNumber={null} onSelect={select} />);
    expect(screen.queryByText(/Answered from/)).toBeNull();
    expect(screen.getByText(/shown without any claim about its sources/)).toBeVisible();
  });

  it("GF1-14 the frontend copy mirrors backend NOTICES and ChatState exactly", () => {
    const source = read("backend/app/services/chat.py");
    const block = source.slice(source.indexOf("NOTICES = {"), source.indexOf("}", source.indexOf("NOTICES = {")));
    expect(block).toContain(`"${BACKEND_NOTICES.no_results}"`);
    for (const [key, text] of Object.entries(BACKEND_NOTICES)) {
      if (key === "partial" || key === "low_confidence") expect(block).toContain(`ChatState.${key.toUpperCase()}.value: "${text}"`);
      else if (key === "scope_violation") expect(block).toContain(`SCOPE_VIOLATION: "${text}"`);
      else expect(block).toContain(`"${key}": "${text}"`);
    }
    const models = read("backend/app/db/models.py");
    const states = models.slice(models.indexOf("class ChatState"), models.indexOf("class", models.indexOf("class ChatState") + 10));
    expect([...states.matchAll(/= "([a-z_]+)"/g)].map((m) => m[1]).sort()).toEqual(["answered", "low_confidence", "partial", "refused"]);
  });
});

describe("GF1-15 per-message sources", () => {
  it("GF1-15 a message's badges and SOURCES row open only its own citation numbers", async () => {
    const onSelect = vi.fn();
    render(<AssistantMessage message={message({ text: "See [1] and [2].", citations: message().citations })} activeNumber={1} onSelect={onSelect} />);
    expect(screen.getByText(/and \[2\]\./)).toBeVisible(); // [2] is not this message's citation: inert text
    const named = screen.getAllByRole("button", { name: "Source 1: notes.pdf, p. 3" });
    expect(named.every((b) => b.getAttribute("aria-pressed") === "true")).toBe(true);
    await userEvent.click(named[named.length - 1]!);
    expect(onSelect.mock.calls[0]![0]).toBe(1);
  });
});

describe("GF1-20 GF1-21 F-M4-03 — Frontend Rendering Safety / F-M3-03 — Prompt Injection Residual", () => {
  it("GF1-20 GF1-21 hostile model, source, refusal and term text renders as inert text everywhere", () => {
    for (const payload of HOSTILE_AI) {
      const fetchSpy = vi.fn();
      vi.stubGlobal("fetch", fetchSpy);
      const citations = [{ number: 1, document_id: "d", file_name: payload, citation_label: payload, page: 1, slide: null, passage: payload, context: payload, low_confidence: false, generated: false }];
      const { container, unmount } = render(
        <>
          <AssistantMessage message={message({ text: `${payload} [1]`, citations })} activeNumber={1} onSelect={() => {}} />
          <AssistantMessage message={message({ id: "m-2", state: "partial", text: payload, citations, missing_terms: [payload] })} activeNumber={null} onSelect={() => {}} />
          <AssistantMessage message={message({ id: "m-3", state: "refused", refusal_reason: "not_relevant", text: payload, citations: [], nearest: [citations[0]!] })} activeNumber={null} onSelect={() => {}} />
          <SourceCard number={1} fileName={payload} location={payload} passage={payload} />
          <SummarySection heading={payload} caption={payload} statements={[payload]} defaultExpanded />
        </>,
      );
      expect(container.querySelector("script, img:not([src=\"/brand/intellistudy-logo.svg\"]), iframe, object, embed")).toBeNull();
      expect([...container.querySelectorAll("a")]).toEqual([]); // no link is ever built from model or document text
      expect(container.textContent).toContain(payload.replace("[1]", ""));
      expect(fetchSpy).not.toHaveBeenCalled();
      unmount();
    }
  });

  it("GF1-20 static bans: no raw-HTML, DOM-parsing or eval APIs in frontend source", () => {
    const banned = /dangerouslySetInnerHTML|\.innerHTML\s*=|outerHTML\s*=|insertAdjacentHTML|DOMParser|\beval\(|new Function\(|document\.write/;
    expect(sourceFiles().filter((f) => banned.test(f.text)).map((f) => f.path)).toEqual([]);
  });

  it("GF1-22 long unbroken text wraps in answers, bubbles, statements and sources", () => {
    const long = "x".repeat(3000);
    const { container } = render(
      <>
        <AssistantMessage message={message({ text: long, question: long })} activeNumber={null} onSelect={() => {}} />
        <SourceCard fileName={long} location="p. 1" passage={long} />
      </>,
    );
    const holders = [...container.querySelectorAll("p, span")].filter((el) => el.textContent === long);
    expect(holders.length).toBeGreaterThanOrEqual(3);
    for (const el of holders) expect(el.className).toMatch(/break-words|wrap-anywhere/);
  });
});

describe("GF1-04 summary polling", () => {
  it("GF1-04 polls about every 2 s only while a generation is pending, with bounded backoff and a stop", () => {
    const base = { pending: true } as SummaryOut;
    expect(summaryPollDelay(base, 0)).toBe(2000);
    expect(summaryPollDelay(base, 3)).toBe(16000);
    expect(summaryPollDelay(base, MAX_POLL_FAILURES)).toBe(false);
    expect(summaryPollDelay({ ...base, pending: false }, 0)).toBe(false);
    expect(summaryPollDelay(null, 0)).toBe(false);
  });
});

describe("GF1-05 GF1-16 error copy", () => {
  const err = (status: number, code: string, retry: string | null = null) => apiErrorFromBody(status, { type: `about:blank#${code}`, detail: "Traceback /srv/app.py" }, retry);
  it("GF1-05 summary failures map to fixed sentences, never the problem body", () => {
    expect(summaryRequestError(err(409, "document_not_ready"))).toMatch(/isn’t ready yet/);
    expect(summaryRequestError(err(503, "llm_unavailable"))).toBe("The AI service is unavailable right now. Try again later.");
    expect(summaryRequestError(err(429, "rate_limited", "120"))).toBe("Too many summary requests in the last hour. Try again in 2 minutes.");
    expect(summaryRequestError(err(429, "token_budget", "3600"))).toBe("Your daily AI budget is used up. Try again tomorrow.");
    expect(summaryRequestError(new ApiError({ kind: "network", status: 0 }))).toMatch(/offline/);
    expect(summaryRequestError(err(500, "boom"))).toBe("That didn’t work. Try again.");
    expect(generationFailure("ungrounded")).toMatch(/No statement could be backed/);
    expect(generationFailure("mystery")).toMatch(/Something went wrong/);
  });

  it("GF1-16 chat send failures map to fixed sentences", () => {
    expect(sendErrorMessage(err(422, "invalid_question"))).toBe("Ask a question of 1-2000 characters.");
    expect(sendErrorMessage(err(429, "rate_limited", "30"))).toBe("You’ve asked many questions in the last minute. Try again in 30 seconds.");
    expect(sendErrorMessage(err(429, "token_budget", "999"))).toBe("Your daily AI budget is used up. Try again tomorrow.");
    expect(sendErrorMessage(new ApiError({ kind: "network", status: 0 }))).toMatch(/Your question is kept/);
    expect(sendErrorMessage(err(404, "not_found"))).toBe("This conversation no longer exists.");
    expect(sendErrorMessage(new Error("x"))).toBe("The question couldn’t be sent. Try again.");
  });
});

describe("GF1-11 GF1-17 GF1-19 conversation helpers and keys", () => {
  it("GF1-17 ?c= accepts only a canonical id; anything else is not found without a request", () => {
    expect(parseConversationParam("11111111-1111-4111-8111-111111111111")).toEqual({ id: "11111111-1111-4111-8111-111111111111", invalid: false });
    expect(parseConversationParam(null)).toEqual({ id: null, invalid: false });
    for (const raw of ["x", "../../etc", "javascript:alert(1)", "11111111-1111-4111-8111-11111111111Z"]) expect(parseConversationParam(raw).invalid).toBe(true);
  });

  it("GF1-11 after a delete the next conversation is chosen, else the previous one, else none", () => {
    const list = ["a", "b", "c"].map((id) => ({ id }) as never);
    expect(neighbourAfterDelete(list, "b")).toBe("c");
    expect(neighbourAfterDelete(list, "c")).toBe("b");
    expect(neighbourAfterDelete([list[0]!], "a")).toBeNull();
  });

  it("GF1-19 keys carry their resource boundary", () => {
    expect(queryKeys.summary("d1")).toEqual(["summary", "d1"]);
    expect(queryKeys.conversationList("c1")).toEqual(["conversations", "c1", { limit: 50 }]);
    expect(queryKeys.conversationList("c1").slice(0, 2)).toEqual(queryKeys.conversationsOf("c1"));
    expect(queryKeys.conversation("x")).toEqual(["conversation", "x"]);
    expect(queryKeys.summary("d1")).not.toEqual(queryKeys.summary("d2"));
  });
});

describe("GF1-26 isolated E2E harness", () => {
  it("GF1-26 the scripts require explicit targets, refuse port 8000, check the build, and clean up", () => {
    const backend = readFileSync(join(process.cwd(), "scripts", "e2e-backend.sh"), "utf8");
    expect(backend).toContain('PORT="${E2E_BACKEND_PORT:?');
    expect(backend).toContain('LLM_PORT="${E2E_LLM_PORT:?');
    expect(backend).toContain('"$p" == "8000"');
    expect(backend).toContain("trap cleanup EXIT");
    expect(backend).toContain("INTELLISTUDY_LLM_PROVIDER=local");
    expect(backend).not.toMatch(/API_KEY|source\s+\S*\.env|--env-file|cat\s+\S*\.env/);
    const frontend = readFileSync(join(process.cwd(), "scripts", "e2e-frontend.sh"), "utf8");
    expect(frontend).toContain('ORIGIN="${INTELLISTUDY_API_ORIGIN:?');
    expect(frontend).toContain('*":8000"');
    expect(frontend).toContain("routes-manifest.json");
    expect(readFileSync(join(process.cwd(), "next.config.ts"), "utf8")).toContain('process.env.INTELLISTUDY_E2E === "1" && !process.env.INTELLISTUDY_API_ORIGIN');
    const config = readFileSync(join(process.cwd(), "playwright.config.ts"), "utf8");
    expect(config).toContain('command: "bash scripts/e2e-frontend.sh"');
    expect(config).not.toContain(":8000");
  });
});
