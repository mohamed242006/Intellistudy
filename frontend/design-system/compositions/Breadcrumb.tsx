import Link from "next/link";

/**
 * Breadcrumb (UI §6.4): `text/caption` secondary, two spaces around "/" as drawn. Parents are links (UI §18 D-5); the
 * current page is plain text with `aria-current="page"`. Labels are rendered as text (F-M4-03).
 */
export function Breadcrumb({ items }: { items: ReadonlyArray<{ label: string; href?: string }> }) {
  return (
    <nav aria-label="Breadcrumb">
      <ol className="flex flex-wrap items-center text-caption text-fg-secondary">
        {items.map((item, index) => (
          <li key={`${index}-${item.label}`} className="flex min-w-0 items-center">
            {index > 0 ? (
              <span aria-hidden="true" className="whitespace-pre">
                {"  /  "}
              </span>
            ) : null}
            {item.href ? (
              <Link href={item.href} className="rounded-sm wrap-anywhere hover:text-fg hover:underline">
                {item.label}
              </Link>
            ) : (
              <span aria-current="page" className="wrap-anywhere">
                {item.label}
              </span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}
