"use client";

import { useEffect, useState } from "react";

/** A CSS media query as state. Without `matchMedia` (tests, old browsers) it returns `fallback`. */
export function useMediaQuery(query: string, fallback = true): boolean {
  const [matches, setMatches] = useState(() => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(query).matches : fallback));
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const list = window.matchMedia(query);
    const update = () => setMatches(list.matches);
    update();
    list.addEventListener("change", update);
    return () => list.removeEventListener("change", update);
  }, [query]);
  return matches;
}
