/** Shell copy. FIGMA = UI §6.2, §10.1. PROVISIONAL = not drawn (sign-out placement, plan decision 11.3-5). */
export const FIGMA = { dashboard: "Dashboard", courses: "Courses", settings: "Settings", brand: "IntelliStudy" } as const;

export const PROVISIONAL = {
  mainNav: "Main",
  account: "Account",
  accountMenu: (name: string) => `Account: ${name}`,
  signOut: "Sign out",
  skipToContent: "Skip to content",
  homeLink: "IntelliStudy, go to Dashboard",
} as const;
