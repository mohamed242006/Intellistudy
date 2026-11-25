import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Button } from "@/design-system/components/Button";
import { Input } from "@/design-system/components/Input";

describe("GF0A-04 Button", () => {
  it("GF0A-04 renders the variants used by Auth with the 44 px control height, and Loading blocks clicks", async () => {
    const onClick = vi.fn();
    const { rerender } = render(<Button variant="primary" onClick={onClick}>Sign in</Button>);
    const button = screen.getByRole("button", { name: "Sign in" });
    expect(button).toHaveAttribute("data-variant", "primary");
    expect(button.className).toContain("h-control-md");
    expect(button.className).toContain("bg-accent");
    await userEvent.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);

    rerender(<Button variant="primary" onClick={onClick} loading>Sign in</Button>);
    expect(button).toHaveAttribute("aria-busy", "true");
    await userEvent.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);

    rerender(<Button variant="secondary" disabled onClick={onClick}>Sign out</Button>);
    const secondary = screen.getByRole("button", { name: "Sign out" });
    expect(secondary).toBeDisabled();
    expect(secondary.className).toContain("border-line-strong");
    rerender(<Button variant="ghost">Why this?</Button>);
    expect(screen.getByRole("button", { name: "Why this?" }).className).toContain("text-accent-fg");
  });
});

describe("GF0A-05 Input", () => {
  it("GF0A-05 binds label and helper, and the Error state sets aria-invalid with a text message", async () => {
    const { rerender } = render(<Input label="University email" helper="Use the address your university gave you" />);
    const field = screen.getByLabelText("University email");
    expect(field).toHaveAccessibleDescription("Use the address your university gave you");
    expect(field).not.toHaveAttribute("aria-invalid");
    await userEvent.click(field);
    expect(field).toHaveFocus();

    rerender(<Input label="University email" helper="Use the address your university gave you" error="Enter a valid email address." />);
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(field).toHaveAccessibleDescription("Enter a valid email address.");
    expect(screen.getByText("Enter a valid email address.")).toBeVisible();

    rerender(<Input label="University email" disabled />);
    expect(screen.getByLabelText("University email")).toBeDisabled();
  });
});
