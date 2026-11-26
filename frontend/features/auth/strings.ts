/**
 * Auth copy. FIGMA = exact strings from docs/DESIGN_SPEC_NEW.md §3.1 (v2.0), earlier docs/figma_ui_context.md §8.1.4.
 * The spec's third trust point ("Quizzes focus on the topics you find hardest") describes personalisation this app does
 * not have, so it is replaced by a true statement about the existing "Retry wrong answers" flow.
 * BACKEND = sentences written by the backend (backend/app/services/auth.py, core/passwords.py).
 * PROVISIONAL = copy Figma does not provide (form-level errors); listed for approval (docs/F0A_GATE.md section 2).
 */

export const FIGMA = {
  brandHeadline: "Study smarter from your own lectures.",
  brandSubcopy: "Upload your course files and get summaries, answers and quizzes that cite the exact page they came from.",
  trustPoints: ["Every answer cites your materials", "Your files stay private to your account", "Retry the quiz questions you missed"],
  tabSignIn: "Sign in",
  tabCreateAccount: "Create account",
  signInTitle: "Welcome back",
  signUpTitle: "Create your account",
  emailLabel: "University email",
  emailPlaceholder: "name@university.edu",
  emailHelper: "Use the address your university gave you",
  passwordLabel: "Password",
  passwordPlaceholderSignIn: "Enter your password",
  fullNameLabel: "Full name",
  signInButton: "Sign in",
  createAccountButton: "Create account",
  forgotPassword: "Forgot your password?",
  legal: "By creating an account you agree to the Terms and the Privacy Policy. Your files stay private to you.",
} as const;

/** Replaces Figma's "At least 12 characters" / "Use 12 or more characters…" to match the backend policy (10-128). */
export const BACKEND_ALIGNED = {
  passwordPlaceholderSignUp: "At least 10 characters",
  passwordHelperSignUp: "Use 10 or more characters, with at least one letter and one number.",
} as const;

export const BACKEND = {
  invalidCredentials: "Invalid email or password.",
  registrationRejected: "Registration could not be completed with these details.",
  invalidEmail: "Enter a valid email address.",
  invalidName: "Enter your name (1-100 characters).",
  passwordTooShort: "Password must be at least 10 characters.",
  passwordTooLong: "Password must be at most 128 characters.",
  passwordNeedsLetter: "Password must contain at least one letter.",
  passwordNeedsDigit: "Password must contain at least one digit.",
  sessionExpired: "Session expired. Sign in again.",
} as const;

export const PROVISIONAL = {
  emailRequired: "Enter your email address.",
  passwordRequired: "Enter your password.",
  rateLimitedSeconds: (seconds: number) => `Too many attempts. Try again in ${seconds} seconds.`,
  rateLimited: "Too many attempts. Try again later.",
  network: "We couldn’t reach IntelliStudy. Check your connection and try again.",
  checkFields: "Check the highlighted fields and try again.",
  unexpected: "Something went wrong. Try again.",
  signedOut: "You’re signed out.",
  resetUnavailable: "Password reset is not available yet.",
} as const;
