"use client";

import { useEffect, useRef } from "react";

/**
 * Checkbox: the real native input (keyboard, forms, `indeterminate`, accessible name) stretched over a 44×44 target,
 * with a drawn box on top. Checking draws the tick (stroke animation, 160 ms); the mixed state shows a dash. Colours
 * come from the accent tokens; the 2 px focus ring follows the keyboard only. Motion is removed under reduced motion.
 */
export function Checkbox({ checked, indeterminate = false, disabled = false, onChange, label, describedBy, testId }: {
  checked: boolean;
  indeterminate?: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
  /** Accessible name (the visible label may be elsewhere in the row). */
  label: string;
  describedBy?: string;
  testId?: string;
}) {
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (input.current) input.current.indeterminate = indeterminate && !checked;
  }, [indeterminate, checked]);
  return (
    <span className="is-checkbox relative inline-flex size-11 shrink-0 items-center justify-center" data-mixed={indeterminate && !checked ? "" : undefined}>
      <input
        ref={input}
        type="checkbox"
        checked={checked}
        disabled={disabled}
        aria-label={label}
        aria-describedby={describedBy}
        data-testid={testId}
        onChange={(event) => onChange(event.target.checked)}
        className="absolute inset-0 z-10 m-0 cursor-pointer opacity-0 disabled:cursor-not-allowed"
      />
      <span aria-hidden="true" className="is-checkbox-box flex size-5 items-center justify-center rounded-[5px] border-2">
        <svg viewBox="0 0 16 16" className="is-checkbox-tick size-3.5" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 8.5 6.5 12 13 4.5" />
        </svg>
        <span className="is-checkbox-dash h-0.5 w-2.5 rounded-full bg-current" />
      </span>
    </span>
  );
}
