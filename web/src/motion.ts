import { useEffect, useRef } from "react";

/**
 * Reveal on scroll. Elements marked with data-reveal start hidden and rise in
 * as they enter the viewport, staggered by their position in a group so a grid
 * lands cell by cell rather than all at once.
 */
export function useScrollReveal() {
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      document
        .querySelectorAll<HTMLElement>("[data-reveal]")
        .forEach((el) => el.classList.add("is-revealed"));
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          const el = entry.target as HTMLElement;
          const delay = Number(el.dataset.revealDelay ?? 0);
          window.setTimeout(() => el.classList.add("is-revealed"), delay);
          observer.unobserve(el);
        });
      },
      { rootMargin: "0px 0px -12% 0px", threshold: 0.12 }
    );

    const watch = () =>
      document
        .querySelectorAll<HTMLElement>("[data-reveal]:not(.is-revealed)")
        .forEach((el) => observer.observe(el));

    watch();
    // Sections mount as state changes, so keep picking up new candidates.
    const rescan = window.setInterval(watch, 1200);
    return () => {
      window.clearInterval(rescan);
      observer.disconnect();
    };
  }, []);
}

/** Cards light up under the cursor: track the pointer as CSS variables. */
export function useSpotlight<T extends HTMLElement>() {
  const ref = useRef<T>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onMove = (e: PointerEvent) => {
      const box = el.getBoundingClientRect();
      el.style.setProperty("--sx", `${e.clientX - box.left}px`);
      el.style.setProperty("--sy", `${e.clientY - box.top}px`);
    };
    el.addEventListener("pointermove", onMove);
    return () => el.removeEventListener("pointermove", onMove);
  }, []);

  return ref;
}
