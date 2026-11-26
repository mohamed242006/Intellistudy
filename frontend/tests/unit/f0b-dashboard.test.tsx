import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CoursesPage from "@/app/(app)/(sidebar)/courses/page";
import DashboardPage from "@/app/(app)/(sidebar)/page";
import { tokenStore } from "@/lib/auth/token-store";
import { deferred, renderPage, signedInBackend } from "../helpers/app";
import { COURSE_ID, HOSTILE, OTHER_ID, course, doc, page } from "../helpers/data";
import { json, problem } from "../helpers/fake-backend";
import { nav } from "../helpers/navigation";
import { sourceFiles } from "./static/scan";

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

const NO_DOCS = () => json(200, page([], 100));
const dashboard = () => renderPage(<DashboardPage />);

describe("GF0B-01 app shell", () => {
  it("GF0B-01 Sidebar lists only built destinations (Dashboard, Courses, Settings), marks the current page, and has nav and main landmarks", async () => {
    signedInBackend().on("GET /courses", () => json(200, page([])));
    dashboard();
    expect(await screen.findByRole("heading", { level: 2, name: "Your courses" })).toBeVisible();
    const navs = screen.getAllByRole("navigation", { name: "Main" });
    for (const navigation of navs) {
      expect(within(navigation).getAllByRole("link").map((a) => a.textContent || a.getAttribute("aria-label"))).toEqual(["Dashboard", "Courses", "Settings"]);
      expect(within(navigation).getByRole("link", { name: "Dashboard" })).toHaveAttribute("aria-current", "page");
      expect(within(navigation).getByRole("link", { name: "Courses" })).toHaveAttribute("href", "/#courses");
      expect(within(navigation).getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings");
    }
    expect(screen.getByRole("main")).toBeVisible();
    expect(screen.queryByRole("link", { name: /Analytics|Personalised exam|Data & privacy/ })).toBeNull();
  });
});

describe("GF0B-04 Dashboard shows real data only", () => {
  it("GF0B-04 greets the signed-in user and shows course cards built from courses and their documents", async () => {
    signedInBackend()
      .on("GET /courses", () => json(200, page([course({ description: "M/M/1 queues." }), course({ id: OTHER_ID, name: "Operating Systems" })])))
      .on(`GET /courses/${COURSE_ID}/documents`, () => json(200, page([doc(), doc({ status: "embedding" })], 100)))
      .on(`GET /courses/${OTHER_ID}/documents`, () => json(200, page([doc({ course_id: OTHER_ID }), doc({ course_id: OTHER_ID })], 100)));
    dashboard();
    expect(await screen.findByRole("heading", { level: 1, name: /^Good (morning|afternoon|evening), Test$/ })).toBeVisible();
    const queueing = await screen.findByRole("link", { name: /Queueing Theory/ });
    expect(queueing).toHaveAttribute("href", `/courses/${COURSE_ID}`);
    await waitFor(() => expect(queueing).toHaveTextContent("Queueing TheoryM/M/1 queues.1 processing2 files"));
    await waitFor(() => expect(screen.getByRole("link", { name: /Operating Systems/ })).toHaveTextContent("All indexed2 files"));
    expect(document.body.textContent).not.toMatch(/mastery|streak|recommended|weakest|recent activity|Practise|\d+%/i);
  });

  it("GF0B-04 no Figma sample data appears anywhere in the frontend source", () => {
    const samples = /Layla|Hassan|Aspect-Oriented|Computer Science · Year 3|Little’s Law|midterm|Lecture 4 —|74% mastery/;
    const offenders = sourceFiles().filter((f) => !f.path.startsWith("design-system/tokens/") && samples.test(f.text)).map((f) => f.path);
    expect(offenders).toEqual([]);
  });
});

describe("GF0B-05 Dashboard states", () => {
  it("GF0B-05 loading shows three Card Loading skeletons in a busy status region", async () => {
    const hold = deferred<void>();
    signedInBackend().on("GET /courses", () => hold.promise.then(() => json(200, page([]))));
    dashboard();
    const busy = await screen.findByRole("status", { name: "Loading your courses" });
    expect(busy).toHaveAttribute("aria-busy", "true");
    expect(busy.querySelectorAll("[data-card-loading]")).toHaveLength(3);
    hold.resolve();
    expect(await screen.findByRole("heading", { name: "No courses yet" })).toBeVisible();
  });

  it("GF0B-05 empty shows the EmptyState with a New course action", async () => {
    signedInBackend().on("GET /courses", () => json(200, page([])));
    dashboard();
    expect(await screen.findByRole("heading", { level: 3, name: "No courses yet" })).toBeVisible();
    expect(screen.getAllByRole("button", { name: "New course" })).toHaveLength(2);
  });

  it("GF0B-05 an error shows a safe message and Try again recovers", async () => {
    let fail = true;
    signedInBackend()
      .on("GET /courses", () => (fail ? problem(500, "internal_error") : json(200, page([course()]))))
      .on(`GET /courses/${COURSE_ID}/documents`, NO_DOCS);
    dashboard();
    expect(await screen.findByText("Couldn’t load your courses.")).toBeVisible();
    expect(document.body.textContent).not.toContain("internal_error");
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("link", { name: /Queueing Theory/ })).toBeVisible();
  });
});

describe("GF0B-06 course pagination", () => {
  it("GF0B-06 loads further pages of 50 on request and never silently truncates", async () => {
    const first = Array.from({ length: 50 }, (_, i) => course({ id: `aaaaaaaa-aaaa-4aaa-8aaa-${String(i).padStart(12, "0")}`, name: `Course ${i}` }));
    const second = [course({ id: "bbbbbbbb-bbbb-4bbb-8bbb-000000000001", name: "Course 50" })];
    const backend = signedInBackend()
      .on("GET /courses", (url) => json(200, url.searchParams.get("offset") === "50" ? page(second, 50, 50) : page(first, 50, 0)))
      .match(/^GET \/courses\/[^/]+\/documents$/, NO_DOCS);
    dashboard();
    expect(await screen.findByRole("link", { name: /Course 49/ })).toBeVisible();
    expect(backend.calls.find((c) => c.path === "/courses")!.search).toBe("?limit=50&offset=0");
    await userEvent.click(screen.getByRole("button", { name: "Show more courses" }));
    expect(await screen.findByRole("link", { name: /Course 50/ })).toBeVisible();
    expect(backend.calls.filter((c) => c.path === "/courses").map((c) => c.search)).toContain("?limit=50&offset=50");
    await waitFor(() => expect(screen.queryByRole("button", { name: "Show more courses" })).toBeNull());
  });
});

describe("GF0B-07 course creation", () => {
  it("GF0B-07 creates with the trimmed name, invalidates only the course list, and opens the new workspace", async () => {
    const created = course({ id: OTHER_ID, name: "Operating Systems" });
    const backend = signedInBackend()
      .on("GET /courses", () => json(200, page([])))
      .on("POST /courses", () => json(201, created));
    const { queryClient } = dashboard();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    await userEvent.click((await screen.findAllByRole("button", { name: "New course" }))[0]!);
    const dialog = screen.getByRole("dialog", { name: "New course" });
    expect(within(dialog).getByLabelText("Course name")).toHaveFocus();
    await userEvent.type(within(dialog).getByLabelText("Course name"), "  Operating Systems  ");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create course" }));
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith(`/courses/${OTHER_ID}`));
    expect(backend.calls.find((c) => c.method === "POST" && c.path === "/courses")!.body).toEqual({ name: "Operating Systems" });
    expect(invalidate.mock.calls.map((c) => c[0]?.queryKey)).toEqual([["courses"]]);
    expect(queryClient.getQueryData(["course", OTHER_ID])).toEqual(created);
  });

  it("GF0B-07 blocks double submission: one POST while the first is pending", async () => {
    const hold = deferred<Response>();
    const backend = signedInBackend().on("GET /courses", () => json(200, page([]))).on("POST /courses", () => hold.promise);
    dashboard();
    await userEvent.click((await screen.findAllByRole("button", { name: "New course" }))[0]!);
    await userEvent.type(screen.getByLabelText("Course name"), "Networks");
    const submit = screen.getByRole("button", { name: "Create course" });
    await userEvent.click(submit);
    await userEvent.click(submit);
    await userEvent.keyboard("{Enter}");
    expect(submit).toHaveAttribute("aria-busy", "true");
    expect(backend.count("POST /courses")).toBe(1);
    hold.resolve(json(201, course({ id: OTHER_ID, name: "Networks" })));
    await waitFor(() => expect(nav.push).toHaveBeenCalledOnce());
  });

  it("GF0B-07 validates like the backend and shows the errors on the field", async () => {
    const backend = signedInBackend().on("GET /courses", () => json(200, page([])));
    dashboard();
    await userEvent.click((await screen.findAllByRole("button", { name: "New course" }))[0]!);
    const input = screen.getByLabelText("Course name");
    await userEvent.type(input, "   ");
    await userEvent.click(screen.getByRole("button", { name: "Create course" }));
    expect(await screen.findByText("Enter a course name.")).toBeVisible();
    expect(input).toHaveAttribute("aria-invalid", "true");
    await userEvent.clear(input);
    await userEvent.click(input);
    await userEvent.paste("x".repeat(201));
    await userEvent.click(screen.getByRole("button", { name: "Create course" }));
    expect(await screen.findByText("Use 200 characters or fewer.")).toBeVisible();
    expect(backend.count("POST /courses")).toBe(0);
  });

  it("GF0B-07 a server 422 marks the field; a network failure keeps the typed name and is announced", async () => {
    let reply = () => json(422, { type: "about:blank#validation_error", title: "x", status: 422, errors: [{ loc: ["body", "name"], type: "string_too_short" }] });
    signedInBackend()
      .on("GET /courses", () => json(200, page([])))
      .on("POST /courses", () => reply());
    dashboard();
    await userEvent.click((await screen.findAllByRole("button", { name: "New course" }))[0]!);
    const input = screen.getByLabelText("Course name");
    await userEvent.type(input, "Networks");
    await userEvent.click(screen.getByRole("button", { name: "Create course" }));
    expect(await screen.findByText("Enter a course name.")).toBeVisible();
    reply = () => {
      throw new TypeError("Failed to fetch");
    };
    await userEvent.click(screen.getByRole("button", { name: "Create course" }));
    const dialog = screen.getByRole("dialog");
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("You appear to be offline. Check your connection and try again.");
    expect(input).toHaveValue("Networks");
    expect(nav.push).not.toHaveBeenCalled();
  });
});

describe("GF0B-08 Upload files on the Dashboard", () => {
  it("GF0B-08 with no course it creates one first, then goes to its upload page", async () => {
    signedInBackend().on("GET /courses", () => json(200, page([]))).on("POST /courses", () => json(201, course()));
    dashboard();
    await userEvent.click(await screen.findByRole("button", { name: "Upload files" }));
    await userEvent.type(screen.getByRole("dialog", { name: "New course" }).querySelector("input")!, "Queueing Theory");
    await userEvent.click(screen.getByRole("button", { name: "Create course" }));
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith(`/courses/${COURSE_ID}/upload`));
  });

  it("GF0B-08 with one course it goes straight to that course's upload page", async () => {
    signedInBackend().on("GET /courses", () => json(200, page([course()]))).on(`GET /courses/${COURSE_ID}/documents`, NO_DOCS);
    dashboard();
    await userEvent.click(await screen.findByRole("button", { name: "Upload files" }));
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith(`/courses/${COURSE_ID}/upload`));
  });

  it("GF0B-08 with several courses it asks which course, as a radio group", async () => {
    signedInBackend()
      .on("GET /courses", () => json(200, page([course(), course({ id: OTHER_ID, name: "Operating Systems" })])))
      .match(/^GET \/courses\/[^/]+\/documents$/, NO_DOCS);
    dashboard();
    await userEvent.click(await screen.findByRole("button", { name: "Upload files" }));
    const dialog = screen.getByRole("dialog", { name: "Choose a course" });
    expect(within(dialog).getByRole("radio", { name: "Queueing Theory" })).toBeChecked();
    await userEvent.click(within(dialog).getByRole("radio", { name: "Operating Systems" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Continue" }));
    expect(nav.push).toHaveBeenCalledWith(`/courses/${OTHER_ID}/upload`);
  });
});

describe("GF0B-09 /courses", () => {
  it("GF0B-09 redirects to the Dashboard's Your courses section", () => {
    nav.reset("/courses");
    try {
      CoursesPage();
    } catch {
      // next/navigation's redirect throws in the real runtime; the mock only records the target
    }
    expect(nav.redirect).toHaveBeenCalledWith("/#courses");
  });
});

describe("GF0B-25 F-M4-03 — Frontend Rendering Safety on the Dashboard", () => {
  it("GF0B-25 hostile course names and descriptions render as text; hrefs stay app routes", async () => {
    const courses = HOSTILE.map((name, i) => course({ id: `cccccccc-cccc-4ccc-8ccc-00000000000${i}`, name, description: name }));
    signedInBackend()
      .on("GET /courses", () => json(200, page(courses)))
      .match(/^GET \/courses\/[^/]+\/documents$/, NO_DOCS);
    dashboard();
    for (const name of HOSTILE) expect((await screen.findAllByText(name)).length).toBe(2);
    expect(document.querySelector("main script, main img")).toBeNull();
    const hrefs = screen.getAllByRole("link").map((a) => a.getAttribute("href") ?? "");
    expect(hrefs.filter((h) => !h.startsWith("/") && h !== "#main")).toEqual([]);
  });
});

describe("GF0B-12 rename keeps the course list honest", () => {
  it("GF0B-12 renaming patches the cached list and still marks it stale, so a list that predates other changes is refetched", async () => {
    const { QueryClient } = await import("@tanstack/react-query");
    const { renderHook, act: hookAct } = await import("@testing-library/react");
    const { QueryClientProvider } = await import("@tanstack/react-query");
    const { useRenameCourse } = await import("@/features/courses/hooks");
    const client = new QueryClient();
    client.setQueryData(["courses", { limit: 50 }], { pages: [page([course()])], pageParams: [0] });
    signedInBackend().on(`PATCH /courses/${COURSE_ID}`, () => json(200, course({ name: "Renamed" })));
    tokenStore.set("t", 900);
    const { result } = renderHook(() => useRenameCourse(COURSE_ID), { wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> });
    await hookAct(async () => {
      await result.current.mutateAsync("Renamed");
    });
    const state = client.getQueryState(["courses", { limit: 50 }])!;
    expect((client.getQueryData(["courses", { limit: 50 }]) as { pages: { items: { name: string }[] }[] }).pages[0]!.items[0]!.name).toBe("Renamed");
    expect(state.isInvalidated).toBe(true);
  });
});
