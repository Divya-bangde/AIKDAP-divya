import { type ClassValue, clsx } from "clsx";
import type { KeyboardEvent } from "react";
import { twMerge } from "tailwind-merge";

/** Merge Tailwind classes, later ones winning on conflict. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** `onKeyDown` for a prompt textarea: Enter submits its form,
 * Shift+Enter still inserts a new line, and Enter while an IME is
 * composing (e.g. Japanese input) is left alone. `requestSubmit` runs
 * native validation and the form's own submit handler, so every guard
 * the form already has still applies. */
export function submitOnEnter(event: KeyboardEvent<HTMLTextAreaElement>) {
  if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
  event.preventDefault();
  event.currentTarget.form?.requestSubmit();
}
