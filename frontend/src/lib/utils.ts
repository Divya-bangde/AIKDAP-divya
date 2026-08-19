import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge Tailwind classes, later ones winning on conflict. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
