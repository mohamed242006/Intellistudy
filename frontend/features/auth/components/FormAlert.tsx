import { Notice } from "@/design-system/components/Notice";

/**
 * Form-level message in a live region that exists before the message does, so screen readers announce it. While empty
 * it is visually hidden (still in the accessibility tree, out of the flex flow), so it adds no gap to the card.
 */
export function FormAlert({ message, tone = "warning" }: { message: string | null; tone?: "warning" | "info" }) {
  return (
    <div role="alert" className="empty:sr-only">
      {message ? <Notice tone={tone} title={message} /> : null}
    </div>
  );
}
