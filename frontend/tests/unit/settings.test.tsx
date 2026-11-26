import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SettingsRoute from "@/app/(app)/(sidebar)/settings/page";
import { tokenStore } from "@/lib/auth/token-store";
import { renderPage, signedInBackend } from "../helpers/app";
import { json, problem, TOKEN, USER } from "../helpers/fake-backend";

vi.mock("next/navigation", async () => (await import("../helpers/navigation")).navigationMock());

beforeEach(() => tokenStore.clear());

const settings = () => renderPage(<SettingsRoute />, { path: "/settings" });
const user = () => userEvent.setup();

/** Settings exposes the backend's account endpoints only: change-password and logout-all (auth.py). */
describe("UI-SETTINGS account settings", () => {
  it("UI-SETTINGS-01 shows the signed-in profile read-only and marks Settings as the current page", async () => {
    signedInBackend();
    settings();
    expect(await screen.findByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
    const profile = screen.getByRole("region", { name: "Profile" });
    expect(within(profile).getByText(USER.name)).toBeVisible();
    expect(within(profile).getByText(USER.email)).toBeVisible();
    expect(within(profile).queryByRole("textbox")).toBeNull();
    for (const navigation of screen.getAllByRole("navigation", { name: "Main" })) {
      expect(within(navigation).getByRole("link", { name: "Settings" })).toHaveAttribute("aria-current", "page");
    }
  });

  it("UI-SETTINGS-02 changing the password sends both passwords once and keeps this tab signed in with the new token", async () => {
    const backend = signedInBackend().on("POST /auth/change-password", () => json(200, TOKEN(7)));
    settings();
    const card = await screen.findByRole("region", { name: "Password" });
    await user().type(within(card).getByLabelText("Current password"), "old-password-1");
    await user().type(within(card).getByLabelText("New password"), "new-password-22");
    await user().type(within(card).getByLabelText("Confirm new password"), "new-password-22");
    await user().click(within(card).getByRole("button", { name: "Change password" }));
    expect(await screen.findByText("Password changed. Other devices were signed out.")).toBeVisible();
    const sent = backend.calls.filter((c) => c.path === "/auth/change-password");
    expect(sent).toHaveLength(1);
    expect(sent[0]!.body).toEqual({ current_password: "old-password-1", new_password: "new-password-22" });
    expect(tokenStore.get()).toBe("access-token-7");
    expect(within(card).getByLabelText("Current password")).toHaveValue("");
  });

  it("UI-SETTINGS-03 checks the new password locally, and shows a wrong current password on its field", async () => {
    const backend = signedInBackend().on("POST /auth/change-password", () => problem(400, "invalid_current_password", "The current password is not correct."));
    settings();
    const card = await screen.findByRole("region", { name: "Password" });
    await user().type(within(card).getByLabelText("Current password"), "old-password-1");
    await user().type(within(card).getByLabelText("New password"), "short1");
    await user().type(within(card).getByLabelText("Confirm new password"), "different1");
    await user().click(within(card).getByRole("button", { name: "Change password" }));
    expect(await within(card).findByText("Password must be at least 10 characters.")).toBeVisible();
    expect(within(card).getByText("The new passwords don’t match.")).toBeVisible();
    expect(backend.count("POST /auth/change-password")).toBe(0);
    await user().clear(within(card).getByLabelText("New password"));
    await user().type(within(card).getByLabelText("New password"), "new-password-22");
    await user().clear(within(card).getByLabelText("Confirm new password"));
    await user().type(within(card).getByLabelText("Confirm new password"), "new-password-22");
    await user().click(within(card).getByRole("button", { name: "Change password" }));
    expect(await within(card).findByText("The current password is not correct.")).toBeVisible();
    expect(within(card).getByLabelText("Current password")).toHaveAttribute("aria-invalid", "true");
  });

  it("UI-SETTINGS-04 sign out of all devices asks first (Cancel focused), then revokes every session and signs out here", async () => {
    const backend = signedInBackend().on("POST /auth/logout-all", () => new Response(null, { status: 204 })).on("POST /auth/logout", () => new Response(null, { status: 204 }));
    settings();
    const card = await screen.findByRole("region", { name: "Signed-in devices" });
    await user().click(within(card).getByRole("button", { name: "Sign out of all devices" }));
    const dialog = await screen.findByRole("dialog", { name: "Sign out of all devices?" });
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    expect(backend.count("POST /auth/logout-all")).toBe(0);
    await user().click(within(dialog).getByRole("button", { name: "Sign out of all devices" }));
    await waitFor(() => expect(backend.count("POST /auth/logout-all")).toBe(1));
    await waitFor(() => expect(tokenStore.get()).toBeNull());
  });
});
