import { describe, expect, it } from "vitest";
import { arrayToText, buildExplanationFromText, buildStructureFromText, textToArray } from "./textFields";
import type { ClinicalStructure, ExplanationDraft } from "./types";

describe("arrayToText / textToArray", () => {
  it("round-trips a non-empty list", () => {
    const items = ["첫 번째", "두 번째"];
    expect(textToArray(arrayToText(items))).toEqual(items);
  });

  it("drops blank lines", () => {
    expect(textToArray("첫 줄\n\n  \n둘째 줄")).toEqual(["첫 줄", "둘째 줄"]);
  });
});

describe("buildStructureFromText", () => {
  const original: ClinicalStructure = {
    problems: [{ text: "기존 문제", certainty: "stated", source_segment_ids: ["seg-1"] }],
    tests: [],
    medications: [],
    plan: [],
    warnings: [],
    follow_up: [],
    questions_or_conflicts: [],
  };

  it("preserves certainty/source ids for lines that still exist", () => {
    const result = buildStructureFromText(original, "기존 문제 수정됨");
    expect(result.problems).toEqual([
      { text: "기존 문제 수정됨", certainty: "stated", source_segment_ids: ["seg-1"] },
    ]);
  });

  it("adds a new problem with no source segments for a clinician-typed line", () => {
    const result = buildStructureFromText(original, "기존 문제\n새로 추가한 문제");
    expect(result.problems[1]).toEqual({
      text: "새로 추가한 문제",
      certainty: "stated",
      source_segment_ids: [],
    });
  });
});

describe("buildExplanationFromText", () => {
  const original: ExplanationDraft = {
    draft_notice: "",
    current_situation: [],
    tests_and_reasons: [],
    treatment_plan: [],
    medication_instructions: [],
    warning_signs: [],
    what_to_do_next: [],
    follow_up: [],
    items_to_confirm_with_clinician: [],
    source_map: [],
  };

  it("applies the notice and every field text", () => {
    const result = buildExplanationFromText(original, "검토 전 초안", {
      current_situation: "혈압이 높습니다",
      warning_signs: "두통\n어지러움",
    });
    expect(result.draft_notice).toBe("검토 전 초안");
    expect(result.current_situation).toEqual(["혈압이 높습니다"]);
    expect(result.warning_signs).toEqual(["두통", "어지러움"]);
  });
});
