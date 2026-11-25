import { useId, type InputHTMLAttributes, type Ref } from "react";
import { Icon } from "../icons/Icon";

/**
 * Input (UI §7.2): Label (`text/label`) → Field (44 high, radius 8, padding 0/16, `text/body`) → Helper (`text/body-sm`).
 * States: Default stroke `border/strong` 1 · Hover `text/tertiary` · Focus 2 px `focus/ring` inside · Error 2 px
 * `danger/solid` with a trailing 20 px icon and a 16 px icon in the helper row · Disabled.
 * The 2 px strokes are drawn as a 1 px border plus a 1 px inset shadow, so the text does not shift.
 */
type InputProps = Omit<InputHTMLAttributes<HTMLInputElement>, "className" | "id"> & {
  label: string;
  helper?: string;
  error?: string;
  ref?: Ref<HTMLInputElement>;
};

export function Input({ label, helper, error, disabled, ref, ...rest }: InputProps) {
  const id = useId();
  const helperId = `${id}-helper`;
  const describedBy = error || helper ? helperId : undefined;
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={id} className={`text-label ${disabled ? "text-disabled-fg" : "text-fg"}`}>
        {label}
      </label>
      <div className="relative">
        <input
          {...rest}
          ref={ref}
          id={id}
          disabled={disabled}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          className={[
            "h-control-md w-full rounded-md border bg-surface px-4 text-body text-fg placeholder:text-fg-tertiary",
            "outline-none focus-visible:outline-none",
            error
              ? "border-danger-solid pr-11 shadow-[inset_0_0_0_1px_var(--color-danger-solid)]"
              : "border-line-strong hover:border-fg-tertiary focus:border-focus-ring focus:shadow-[inset_0_0_0_1px_var(--color-focus-ring)]",
            "disabled:cursor-not-allowed disabled:border-line disabled:bg-disabled-bg disabled:text-disabled-fg disabled:placeholder:text-disabled-fg",
          ].join(" ")}
        />
        {error ? <Icon name="alert" size={20} className="pointer-events-none absolute top-3 right-4" /> : null}
      </div>
      {error ? (
        <p id={helperId} className="flex items-start gap-1 text-body-sm text-danger-fg">
          <Icon name="alert" size={16} className="mt-0.5" />
          <span>{error}</span>
        </p>
      ) : helper ? (
        <p id={helperId} className={`text-body-sm ${disabled ? "text-disabled-fg" : "text-fg-secondary"}`}>
          {helper}
        </p>
      ) : null}
    </div>
  );
}
