/** Course Workspace copy (selection, focus card, summary states). Counts are always grammatical. */
const files = (n: number) => (n === 1 ? "1 file" : `${n} files`);

export const WORKSPACE = {
  selectAll: "Select all",
  clear: "Clear",
  ofSelected: (n: number, total: number) => `${n} of ${files(total)} selected`,
  selected: (n: number) => `${files(n)} selected`,
  notSelectable: (status: string) => `Can’t be selected: ${status.toLowerCase()}. Only ready files can be used for summaries, quizzes and questions.`,
  filter: "Filter files",
  noMatch: "No file matches this filter.",
  previewPrefix: "Preview ",
  check: (name: string) => `Select ${name}`,
  // focus card: nothing checked
  overviewTitle: "Study this course",
  overviewBody: "Tick files in Materials to summarise them together, build a quiz from them, or ask questions about just those files.",
  overviewNoReady: "Your files are still being processed. They can be selected as soon as they are ready.",
  stats: { files: "Files", ready: "Ready", summaries: "Combined summaries", quizzes: "Quizzes" },
  recentSummaries: "Recent combined summaries",
  recentQuizzes: "Recent quizzes",
  allSummaries: "All summaries",
  allQuizzes: "All quizzes",
  noSummaries: "No combined summary yet. Select two or more files to create one.",
  noQuizzes: "No quiz yet. Select files and choose Create quiz.",
  startTitle: "Start with your materials",
  startBody: "Upload lecture slides, notes or papers. Summaries, quizzes and answers are built only from these files.",
  // focus card: files checked
  selectionTitle: (n: number) => `${files(n)} selected`,
  selectionExplain: (n: number) =>
    n === 1
      ? "A summary of this file cites its pages. A quiz writes questions only from it."
      : `One combined summary covers all ${n} files, grouped by file, and every statement cites its file and page. A quiz draws its questions from all ${n}.`,
  createSummary: (n: number) => (n === 1 ? "Create summary" : "Create combined summary"),
  creatingSummary: "Creating summary…",
  createQuiz: "Create quiz",
  askSelected: "Ask selected materials",
  clearSelection: "Clear selection",
  remove: (name: string) => `Remove ${name} from the selection`,
  // summary states for the previewed file
  summaryCreate: "Create summary",
  summaryProcessing: "Summary processing…",
  summaryRetry: "Retry summary",
  summaryOpen: "Open summary",
  summaryChecking: "Checking summary…",
  summaryView: "View progress",
  // misc
  courseActions: "Course actions",
  ask: "Ask your materials",
} as const;
