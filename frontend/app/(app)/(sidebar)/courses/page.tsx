import { redirect } from "next/navigation";

/** No Courses frame exists (plan decision 11.3-4): the Dashboard's "Your courses" section is the course list. */
export default function CoursesPage(): never {
  redirect("/#courses");
}
