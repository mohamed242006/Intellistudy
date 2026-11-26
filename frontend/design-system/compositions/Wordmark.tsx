import Image from "next/image";
import { BRAND } from "../brand";

/**
 * BrandMark: the logo mark from public/brand (a placeholder until the final logo exists, see design-system/brand.ts).
 * Decorative by default (alt=""): it always sits next to the visible name or inside a control with its own label.
 * Pass `label` only where the mark stands alone and carries meaning. SVG is served as is (`unoptimized`).
 */
export function BrandMark({ size = 32, label, className = "" }: { size?: number; label?: string; className?: string }) {
  return (
    <Image
      src={BRAND.logoSrc}
      alt={label ?? ""}
      width={size}
      height={size}
      unoptimized
      priority={size >= 32}
      className={`shrink-0 rounded-md ${className}`}
    />
  );
}

/** Wordmark (spec §10.2): 32×32 mark + "IntelliStudy" `text/title`, gap 12. */
export function Wordmark({ markOnly = false }: { markOnly?: boolean } = {}) {
  if (markOnly) return <BrandMark />;
  return (
    <div className="flex h-8 items-center gap-3">
      <BrandMark />
      <span className="text-title text-fg">{BRAND.name}</span>
    </div>
  );
}
