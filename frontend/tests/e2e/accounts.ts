/**
 * Accounts of one E2E run. The backend allows 3 registrations per hour per IP, and auth.spec.ts plus courses.spec.ts
 * already use them; grounded.spec.ts (F1) therefore signs in with the accounts courses.spec.ts registered.
 * Files run in alphabetical order with one worker: auth → courses → grounded.
 */
const RUN = process.env.E2E_RUN_ID ?? "local";
export const PASSWORD = "lectures4ever-f0b";
export const ALICE = { name: "Alice Student", email: `alice-${RUN}@example.org` };
export const BOB = { name: "Bob Student", email: `bob-${RUN}@example.org` };
