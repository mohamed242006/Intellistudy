/**
 * Course copy. FIGMA = exact strings from docs/figma_ui_context.md (UI §7.14, §7.15, §8.2, §10.2).
 * PROVISIONAL = copy Figma does not provide; listed for approval (docs/F0B_GATE.md section 3).
 */

export const FIGMA = {
  yourCourses: "Your courses",
  newCourse: "New course",
  uploadFiles: "Upload files",
  allIndexed: "All indexed",
  cancel: "Cancel",
  deleteCourseTitle: "Delete this course?",
  deleteCourse: "Delete course",
  saveChanges: "Save changes",
  courses: "Courses",
} as const;

export const PROVISIONAL = {
  createCourseTitle: "New course",
  createCourse: "Create course",
  renameCourseTitle: "Rename course",
  rename: "Rename",
  courseNameLabel: "Course name",
  courseNameHelper: "For example, the module name on your timetable.",
  courseNameRequired: "Enter a course name.",
  courseNameTooLong: "Use 200 characters or fewer.",
  deleteCourseBody: (files: string) => `This removes ${files}, their summaries, chat history and quiz results. This can’t be undone.`,
  allFiles: "all its files",
  noFilesYet: "No files yet",
  processing: (n: number) => `${n} processing`,
  needAttention: (n: number) => `${n} need attention`,
  moreFiles: (n: number) => `${n}+ files`,
  emptyTitle: "No courses yet",
  emptyBody: "Create a course for each module, then upload its lecture files (PDF, Word, PowerPoint). Summaries, chat and quizzes will be built only from these files.",
  loadError: "Couldn’t load your courses.",
  loadErrorBody: "Check your connection and try again.",
  tryAgain: "Try again",
  showMore: "Show more courses",
  loadingCourses: "Loading your courses",
  chooseCourseTitle: "Choose a course",
  chooseCourseBody: "Files are added to one course at a time.",
  continue: "Continue",
  courseDeleted: "Course deleted.",
  courseRenamed: "Course renamed.",
  notFoundTitle: "Course not found",
  notFoundBody: "This course doesn’t exist or isn’t available to your account.",
  backToDashboard: "Back to Dashboard",
} as const;

/** Form-level errors of the course dialogs (provisional). */
export const COURSE_ERRORS = {
  saveFailed: "The course couldn’t be saved. Try again.",
  offline: "You appear to be offline. Check your connection and try again.",
  deleteFailed: "The course couldn’t be deleted. Try again.",
  gone: "This course no longer exists.",
  rateLimited: "Too many requests. Wait a moment and try again.",
} as const;
