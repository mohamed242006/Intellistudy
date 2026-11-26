import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SourceCard } from "@/design-system/components/SourceCard";
import { Wordmark } from "@/design-system/compositions/Wordmark";
import { BRAND } from "@/design-system/brand";
import { AssistantMessage, answerAsText, type ChatContext } from "@/features/chat/components/ChatMessage";
import { followUps, isVagueReference, scopedQuestion, starterQuestions } from "@/features/chat/clarify";
import { message } from "../helpers/f1-data";

/**
 * UI v2 (docs/DESIGN_SPEC_NEW.md): chat guidance after "not found", source wrapping and clamping, copy, brand mark.
 * The guidance never changes what the backend answered: a refusal stays a refusal with no answer text added.
 */

const FILES = [
  { id: "d-1", file_name: "Lecture 6 — Weaving.pdf" },
  { id: "d-2", file_name: "queueing-notes.pptx" },
];

function context(overrides: Partial<ChatContext> = {}): ChatContext {
  return { courseId: "c-1", files: FILES, onSuggest: vi.fn(), onCopy: vi.fn(), ...overrides };
}

const LONG = "Little's law relates arrivals and time in system. ".repeat(12);
const nearest = (n: number) =>
  Array.from({ length: n }, (_, i) => ({
    number: i + 1, document_id: `d-${i + 1}`, file_name: FILES[i % 2]!.file_name, citation_label: `Page ${i + 3}`, page: i + 3, slide: null,
    passage: i === 0 ? LONG : "Short passage.", context: "", low_confidence: false, generated: false,
  }));

describe("UI-CHAT-01 vague questions are recognised from the question alone", () => {
  it("UI-CHAT-01 a place without a file or a page number is vague; naming either is not", () => {
    const names = FILES.map((f) => f.file_name);
    expect(isVagueReference("explain the first paragraph content", names)).toBe(true);
    expect(isVagueReference("What does this slide say?", names)).toBe(true);
    expect(isVagueReference("explain the first paragraph on page 3", names)).toBe(false);
    expect(isVagueReference("explain the first paragraph of queueing-notes", names)).toBe(false);
    expect(isVagueReference("What is Little's law?", names)).toBe(false);
    expect(scopedQuestion("  explain the first paragraph ", "a.pdf")).toBe("In “a.pdf”: explain the first paragraph");
  });

  it("UI-CHAT-02 follow-ups come only from the backend's closest material; starters only from ready files", () => {
    expect(followUps([{ file_name: "a.pdf", citation_label: "Page 3" }, { file_name: "a.pdf", citation_label: "Page 3" }, { file_name: "b.pdf", citation_label: "Slide 2" }])).toEqual([
      "Explain page 3 of “a.pdf”.",
      "Explain slide 2 of “b.pdf”.",
    ]);
    expect(followUps([])).toEqual([]);
    expect(starterQuestions(["a.pdf", "b.pdf", "c.pdf", "d.pdf"])).toHaveLength(3);
    expect(starterQuestions([])).toEqual([]);
  });
});

describe("UI-CHAT-03 a refusal stays a refusal, with guidance to ask again", () => {
  it("UI-CHAT-03 vague question: clarification with the ready files as choices; a choice fills the composer only", async () => {
    const ctx = context();
    const refused = message({ state: "refused", refusal_reason: "not_relevant", question: "explain the first paragraph content", text: "Your materials don't cover this question, so no answer was generated.", citations: [], nearest: nearest(2) });
    render(<AssistantMessage message={refused} activeNumber={null} onSelect={() => {}} context={ctx} />);
    expect(screen.getByText("I couldn’t find this in your materials")).toBeVisible();
    expect(screen.getByText("Which document and page do you want me to explain?")).toBeVisible();
    const choices = screen.getByText("YOUR READY FILES").parentElement!;
    expect(within(choices).getAllByRole("button").map((b) => b.textContent)).toEqual(FILES.map((f) => f.file_name));
    await userEvent.click(within(choices).getByRole("button", { name: "queueing-notes.pptx" }));
    expect(ctx.onSuggest).toHaveBeenCalledWith("In “queueing-notes.pptx”: explain the first paragraph content");
    // no answer, no citation badges, no copy action on a refusal
    expect(screen.queryByRole("button", { name: /^Source \d/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Copy answer" })).toBeNull();
  });

  it("UI-CHAT-04 closest material is secondary, clamped with Show more / Show less, and links to the file in the course", async () => {
    const refused = message({ state: "refused", refusal_reason: "no_results", question: "What is on the exam?", text: "Nothing matches.", citations: [], nearest: nearest(4) });
    render(<AssistantMessage message={refused} activeNumber={null} onSelect={() => {}} context={context()} />);
    expect(screen.queryByText("Which document and page do you want me to explain?")).toBeNull(); // not vague
    expect(screen.getByText("CLOSEST MATERIAL")).toBeVisible();
    expect(screen.getAllByRole("link", { name: /^Open file\b/ })).toHaveLength(3); // at most 3 cards
    expect(screen.getAllByRole("link", { name: /^Open file\b/ })[0]).toHaveAttribute("href", "/courses/c-1?file=d-1");
    const more = screen.getByRole("button", { name: "Show more" });
    expect(more).toHaveAttribute("aria-expanded", "false");
    const passage = document.getElementById(more.getAttribute("aria-controls")!)!;
    expect(passage.className).toContain("line-clamp-5");
    await userEvent.click(more);
    expect(screen.getByRole("button", { name: "Show less" })).toHaveAttribute("aria-expanded", "true");
    expect(passage.className).not.toContain("line-clamp-5");
    expect(screen.getByText("TRY ASKING")).toBeVisible();
    expect(screen.getByRole("button", { name: "Explain page 3 of “Lecture 6 — Weaving.pdf”." })).toBeVisible();
  });

  it("UI-CHAT-05 the answering service being down offers no guesses and no closest material", () => {
    const down = message({ state: "refused", refusal_reason: "llm_unavailable", question: "explain this slide", text: "Unavailable.", citations: [], nearest: nearest(2) });
    render(<AssistantMessage message={down} activeNumber={null} onSelect={() => {}} context={context()} />);
    expect(screen.queryByText("CLOSEST MATERIAL")).toBeNull();
    expect(screen.queryByText("Which document and page do you want me to explain?")).toBeNull();
    expect(screen.queryByText("TRY ASKING")).toBeNull();
  });
});

describe("UI-CHAT-06 answers: copy, sources that wrap by word, the brand avatar", () => {
  it("UI-CHAT-06 Copy answer copies the text with its markers and the numbered sources", async () => {
    const ctx = context();
    const answered = message();
    render(<AssistantMessage message={answered} activeNumber={null} onSelect={() => {}} context={ctx} />);
    await userEvent.click(screen.getByRole("button", { name: "Copy answer" }));
    expect(ctx.onCopy).toHaveBeenCalledWith("Little's Law relates arrivals and time [1].\n\nSOURCES\n[1] notes.pdf · p. 3");
    expect(answerAsText({ text: "No sources.", citations: [] })).toBe("No sources.");
  });

  it("UI-CHAT-07 file names never split letter by letter: overflow-wrap anywhere, never break-all", () => {
    const { container } = render(<SourceCard number={1} fileName="Lecture 6 — Weaving.pdf" location="Page 12" passage="Short." />);
    const answered = render(<AssistantMessage message={message()} activeNumber={null} onSelect={() => {}} />);
    for (const root of [container, answered.container]) {
      expect(root.querySelector(".break-all")).toBeNull();
      expect(root.querySelector(".wrap-anywhere")).not.toBeNull();
    }
  });

  it("UI-BRAND-01 the mark is the logo file from one place, decorative next to the visible name", () => {
    render(<Wordmark />);
    const img = document.querySelector("img")!;
    expect(img.getAttribute("src")).toBe(BRAND.logoSrc);
    expect(img).toHaveAttribute("alt", "");
    expect(screen.getByText("IntelliStudy")).toBeVisible();
  });
});
