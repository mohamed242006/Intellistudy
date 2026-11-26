/**
 * Settings copy. FIGMA = docs/DESIGN_SPEC_NEW.md §3.14 (header, Profile card). Only what the backend supports is shown:
 * the profile is read-only (no update endpoint); study preferences, appearance and notifications are not built.
 * PROVISIONAL = not drawn (password and sessions cards).
 */
export const FIGMA = {
  title: "Settings",
  profile: "Profile",
  fullName: "Full name",
  email: "University email",
} as const;

export const PROVISIONAL = {
  subtitle: "Your account details, password and signed-in devices.",
  profileNote: "Your name and email can’t be changed here yet.",
  password: "Password",
  passwordIntro: "Changing your password signs you out on every other device.",
  currentPassword: "Current password",
  newPassword: "New password",
  newPasswordHelper: "10–128 characters, with at least one letter and one digit",
  confirmPassword: "Confirm new password",
  mismatch: "The new passwords don’t match.",
  samePassword: "Choose a password different from your current one.",
  changePassword: "Change password",
  changed: "Password changed. Other devices were signed out.",
  wrongCurrent: "The current password is not correct.",
  sessions: "Signed-in devices",
  sessionsIntro: "Sign out everywhere, including this browser. Use it if you signed in on a shared or lost device.",
  logoutAll: "Sign out of all devices",
  logoutAllTitle: "Sign out of all devices?",
  logoutAllBody: "Every device signed in to this account, including this one, will need to sign in again.",
  cancel: "Cancel",
  failed: "That didn’t work. Try again.",
  rateLimited: "Too many attempts. Wait a moment, then try again.",
} as const;
