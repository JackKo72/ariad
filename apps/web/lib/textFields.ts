// Pure text <-> structured-field conversions used by the clinician edit form.
// Extracted so they can be unit tested without mounting the page.

import type { ClinicalStructure, ExplanationDraft } from "./types";

export function arrayToText(items: string[]): string {
  return items.join("\n");
}

export function textToArray(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

export function buildStructureFromText(
  original: ClinicalStructure,
  problemsText: string,
): ClinicalStructure {
  const lines = textToArray(problemsText);
  return {
    ...original,
    problems: lines.map((text, i) => ({
      text,
      certainty: original.problems[i]?.certainty ?? "stated",
      source_segment_ids: original.problems[i]?.source_segment_ids ?? [],
    })),
  };
}

export function buildExplanationFromText(
  original: ExplanationDraft,
  draftNotice: string,
  fieldTexts: Record<string, string>,
): ExplanationDraft {
  const updated: ExplanationDraft = { ...original, draft_notice: draftNotice };
  for (const field of Object.keys(fieldTexts)) {
    (updated as unknown as Record<string, string[]>)[field] = textToArray(fieldTexts[field]);
  }
  return updated;
}
