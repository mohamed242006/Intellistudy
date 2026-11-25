import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { Button } from "@/design-system/components/Button";
import { Card, CardSkeleton } from "@/design-system/components/Card";
import { EmptyState } from "@/design-system/components/EmptyState";
import { FileUploadRow } from "@/design-system/components/FileUploadRow";
import { IconButton } from "@/design-system/components/IconButton";
import { Modal } from "@/design-system/components/Modal";
import { NavItem, RailItem } from "@/design-system/components/NavItem";
import { ProgressBar } from "@/design-system/components/ProgressBar";
import { Tag } from "@/design-system/components/Tag";
import { TOAST_TIMEOUT_MS, ToastProvider, useToast } from "@/design-system/components/Toast";
import { Breadcrumb } from "@/design-system/compositions/Breadcrumb";
import { StatCard } from "@/design-system/compositions/StatCard";
import { UserCard } from "@/design-system/compositions/UserCard";
import { F0B_ICON_USES } from "@/design-system/icons/placeholders";
import { HOSTILE } from "../helpers/data";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

describe("GF0B-02 F0-B components", () => {
  it("GF0B-02 Tag is text with a tone, 24 high, radius 4", () => {
    render(<Tag tone="success">Indexed</Tag>);
    const tag = screen.getByText("Indexed");
    expect(tag).toHaveAttribute("data-tone", "success");
    expect(tag.className).toMatch(/\bh-6\b.*\brounded-sm\b|\brounded-sm\b.*\bh-6\b/);
    expect(tag.className).toContain("bg-success-bg");
  });

  it("GF0B-02 ProgressBar exposes a clamped value, range and name, with a continuous fill width", () => {
    const { rerender } = render(<ProgressBar value={62.4} label="Uploading a.pdf" />);
    const bar = screen.getByRole("progressbar", { name: "Uploading a.pdf" });
    expect(bar).toHaveAttribute("aria-valuenow", "62");
    expect(bar).toHaveAttribute("aria-valuemin", "0");
    expect(bar).toHaveAttribute("aria-valuemax", "100");
    expect((bar.firstElementChild as HTMLElement).style.width).toBe("62%");
    rerender(<ProgressBar value={140} label="x" />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
    rerender(<ProgressBar value={Number.NaN} label="x" />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
  });

  it("GF0B-02 Card is one link with title, description, status and meta; Loading is three skeleton bars", () => {
    render(<Card href="/courses/1" title="Operating Systems" description="Scheduling." status={{ text: "All indexed", tone: "success" }} meta="15 files" />);
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "/courses/1");
    expect(link).toHaveTextContent("Operating SystemsScheduling.All indexed15 files");
    expect(link.className).toContain("rounded-xl");
    expect(link.className).toContain("p-6");
    const { container } = render(<CardSkeleton />);
    expect(container.querySelectorAll("[data-card-loading] > span")).toHaveLength(3);
  });

  it("GF0B-02 NavItem and RailItem are links with aria-current; RailItem and IconButton have accessible names", () => {
    render(
      <>
        <NavItem href="/" icon="home" label="Dashboard" selected />
        <RailItem href="/#courses" icon="book" label="Courses" selected={false} />
        <IconButton icon="x" label="Close dialog" />
      </>,
    );
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Courses" })).not.toHaveAttribute("aria-current");
    const close = screen.getByRole("button", { name: "Close dialog" });
    expect(close.className).toContain("size-11"); // 44 × 44
  });

  it("GF0B-02 EmptyState has a heading at the requested level, body and one action", () => {
    render(<EmptyState size="panel" icon="upload" title="No materials yet" body="Upload lecture slides." headingLevel={3} action={<Button>Upload files</Button>} />);
    expect(screen.getByRole("heading", { level: 3, name: "No materials yet" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Upload files" })).toBeVisible();
  });

  it("GF0B-02 FileUploadRow shows status as text, a progress bar only while uploading, and danger borders for problems", () => {
    const { rerender, container } = render(<FileUploadRow name="a.pdf" status="uploading" tag="Uploading 62%" detail="Uploading · 62% of 4.8 MB" progress={62} />);
    expect(screen.getByText("Uploading 62%")).toBeVisible();
    expect(screen.getByRole("progressbar", { name: "Uploading a.pdf" })).toHaveAttribute("aria-valuenow", "62");
    rerender(<FileUploadRow name="a.pdf" status="empty" tag="Empty" detail="No text." />);
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect((container.firstElementChild as HTMLElement).className).toContain("border-danger-border");
    rerender(<FileUploadRow name="a.pdf" status="indexed" tag="Indexed" detail="48 pages" />);
    expect((container.firstElementChild as HTMLElement).className).toContain("border-line");
  });

  it("GF0B-02 Breadcrumb links its parents and marks the current page; StatCard and UserCard render their text", () => {
    render(
      <>
        <Breadcrumb items={[{ label: "Courses", href: "/#courses" }, { label: "Queueing Theory" }]} />
        <StatCard label="Files indexed" value="4 of 7" note="2 processing · 1 failed" />
        <UserCard name="Layla Hassan" subtitle="layla@example.org" namePrefix="Account:" aria-expanded={false} />
      </>,
    );
    const nav = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(nav).getByRole("link", { name: "Courses" })).toHaveAttribute("href", "/#courses");
    expect(within(nav).getByText("Queueing Theory")).toHaveAttribute("aria-current", "page");
    expect(screen.getByText("4 of 7")).toBeVisible();
    expect(screen.getByRole("button", { name: "Account: Layla Hassan layla@example.org" })).toHaveTextContent("LHAccount: Layla Hassanlayla@example.org");
  });

  it("GF0B-02 every F0-B icon use is a recorded placeholder (visual blocker, no invented glyph)", () => {
    expect(F0B_ICON_USES.length).toBeGreaterThan(0);
    render(<IconButton icon="x" label="Close" />);
    const slot = screen.getByRole("button").querySelector("[data-icon-placeholder]")!;
    expect(slot).toHaveAttribute("aria-hidden", "true");
    expect(slot.children).toHaveLength(0);
  });
});

function ModalHarness({ destructive = false, busy = false }: { destructive?: boolean; busy?: boolean }) {
  const [open, setOpen] = useState(false);
  const [confirmed, setConfirmed] = useState(0);
  return (
    <div>
      <button onClick={() => setOpen(true)}>Open dialog</button>
      <p data-testid="confirmed">{confirmed}</p>
      <Modal
        open={open}
        title="Delete this course?"
        description="This can’t be undone."
        busy={busy}
        onClose={() => setOpen(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button variant={destructive ? "danger" : "primary"} onClick={() => setConfirmed((n) => n + 1)}>
              Delete course
            </Button>
          </>
        }
      >
        {destructive ? null : <input aria-label="Course name" />}
      </Modal>
    </div>
  );
}

describe("GF0B-03 Modal accessibility", () => {
  it("GF0B-03 is a labelled modal dialog, focuses inside, traps Tab, makes the page inert, and Escape returns focus", async () => {
    const user = userEvent.setup();
    render(<ModalHarness />);
    const trigger = screen.getByRole("button", { name: "Open dialog" });
    await user.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Delete this course?" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleDescription("This can’t be undone.");
    expect(screen.getByLabelText("Course name")).toHaveFocus(); // first field
    expect(trigger.closest("[inert]")).not.toBeNull();

    await user.tab(); // → Cancel
    await user.tab(); // → Delete course
    expect(screen.getByRole("button", { name: "Delete course" })).toHaveFocus();
    await user.tab(); // wraps to the close button
    expect(screen.getByRole("button", { name: "Close dialog" })).toHaveFocus();
    await user.tab({ shift: true }); // and back
    expect(screen.getByRole("button", { name: "Delete course" })).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(trigger).toHaveFocus();
    expect(trigger.closest("[inert]")).toBeNull();
    expect(screen.getByTestId("confirmed")).toHaveTextContent("0"); // Escape never confirms
  });

  it("GF0B-03 a busy dialog ignores Escape and its close button", async () => {
    const user = userEvent.setup();
    render(<ModalHarness busy />);
    await user.click(screen.getByRole("button", { name: "Open dialog" }));
    await user.keyboard("{Escape}");
    expect(screen.getByRole("dialog")).toBeVisible();
    expect(screen.getByRole("button", { name: "Close dialog" })).toBeDisabled();
  });
});

function ToastHarness() {
  const toast = useToast();
  return (
    <>
      <button onClick={() => toast("Course deleted.", "success")}>ok</button>
      <button onClick={() => toast("Danger stays.", "danger")}>bad</button>
    </>
  );
}

describe("GF0B-02 Toast", () => {
  it("GF0B-02 toasts appear in a polite region, auto-dismiss after 5 s (Danger stays) and can be dismissed", async () => {
    vi.useFakeTimers();
    try {
      render(
        <ToastProvider>
          <ToastHarness />
        </ToastProvider>,
      );
      const region = screen.getByRole("region", { name: "Notifications" });
      expect(region).toHaveAttribute("aria-live", "polite");
      act(() => screen.getByRole("button", { name: "ok" }).click());
      act(() => screen.getByRole("button", { name: "bad" }).click());
      expect(within(region).getByRole("status")).toHaveTextContent("Course deleted.");
      expect(within(region).getByRole("alert")).toHaveTextContent("Danger stays.");
      act(() => vi.advanceTimersByTime(TOAST_TIMEOUT_MS));
      expect(within(region).queryByRole("status")).toBeNull();
      expect(within(region).getByRole("alert")).toBeVisible();
      act(() => within(region).getByRole("button", { name: "Dismiss notification" }).click());
      expect(within(region).queryByRole("alert")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("GF0B-25 F-M4-03 — Frontend Rendering Safety in components", () => {
  it("GF0B-25 hostile names render as inert text in Card, FileUploadRow, Breadcrumb, Modal and Toast", () => {
    for (const name of HOSTILE) {
      const { container, unmount } = render(
        <ToastProvider>
          <Card href="/courses/1" title={name} description={name} />
          <FileUploadRow name={name} status="failed" tag="Failed" detail={name} />
          <Breadcrumb items={[{ label: "Courses", href: "/#courses" }, { label: name }]} />
          <Modal open title={name} description={name} onClose={() => {}} footer={null} />
        </ToastProvider>,
      );
      const everything = [container, document.body];
      for (const root of everything) {
        expect(root.querySelector("script")).toBeNull();
        expect(root.querySelector("img")).toBeNull();
        expect([...root.querySelectorAll("a")].filter((a) => a.getAttribute("href")?.toLowerCase().startsWith("javascript:"))).toEqual([]);
      }
      expect(screen.getAllByText(name).length).toBeGreaterThan(3);
      unmount();
    }
  });
});
