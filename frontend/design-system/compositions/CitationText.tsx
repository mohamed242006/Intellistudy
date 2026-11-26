import { Fragment } from "react";
import { parseCitations } from "@/lib/citations/parse";
import { CitationBadge } from "../components/CitationBadge";

/**
 * Text with inline citation badges (gate GF1-07). Every string is a React text child (F-M4-03); markers become badges
 * only for numbers of this owner's citations; unknown and malformed markers stay as the text they are.
 */
export function CitationText({ text, labels, activeNumber, onSelect }: {
  text: string;
  /** number → accessible name, for this owner's citations only */
  labels: ReadonlyMap<number, string>;
  activeNumber: number | null;
  onSelect: (number: number, trigger: HTMLButtonElement) => void;
}) {
  const segments = parseCitations(text, new Set(labels.keys()));
  return (
    <>
      {segments.map((segment, index) =>
        segment.kind === "text" ? (
          <Fragment key={index}>{segment.text}</Fragment>
        ) : (
          <CitationBadge
            key={index}
            number={segment.number}
            label={labels.get(segment.number)!}
            active={activeNumber === segment.number}
            onSelect={(trigger) => onSelect(segment.number, trigger)}
          />
        ),
      )}
    </>
  );
}
