"use client";

// tasks/10_CLINICAL_FRAME_AND_REVIEW.md: read-only view of the structure
// slots added for real ICU/ER encounters, plus the clinician review
// checklist. Approval stays disabled (and the API refuses it) until every
// checklist item is checked.

import {
  CLINICAL_FRAME_LABELS,
  type ClinicalFrameId,
  type ClinicalStructure,
  type DecisionStatus,
  type ReviewItem,
} from "@/lib/types";

const DECISION_STATUS_LABELS: Record<DecisionStatus, string> = {
  decided_to_do: "시행",
  decided_not_to_do: "하지 않음",
  conditional: "조건부",
  undecided: "미결정",
};

const FAMILY_KIND_LABELS = { report: "진술", question: "질문", request: "요청" } as const;
const SPEAKER_ROLE_LABELS = { guardian: "보호자", patient: "환자", unknown: "화자" } as const;

function TextList({ title, testId, items }: { title: string; testId: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div data-testid={testId}>
      <strong>{title}</strong>
      <ul className="field-list">
        {items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

export default function ClinicalReviewPanel({
  structure,
  clinicalFrame,
  checklist,
  checkedIds,
  onToggle,
  readOnly,
}: {
  structure: ClinicalStructure;
  clinicalFrame: ClinicalFrameId | null;
  checklist: ReviewItem[];
  checkedIds: Set<string>;
  onToggle: (id: string) => void;
  readOnly: boolean;
}) {
  const decisions = structure.decisions.map((d) => {
    let text = `[${DECISION_STATUS_LABELS[d.status]}] ${d.text}`;
    if (d.condition) text += ` (조건: ${d.condition})`;
    if (d.rationale) text += ` (이유: ${d.rationale})`;
    return text;
  });
  const family = structure.family_statements.map(
    (f) => `${SPEAKER_ROLE_LABELS[f.speaker_role]} ${FAMILY_KIND_LABELS[f.kind]}: ${f.text}`,
  );

  return (
    <div data-testid="clinical-review-panel">
      <p>
        진료 틀: <span data-testid="clinical-frame-label">{clinicalFrame ? CLINICAL_FRAME_LABELS[clinicalFrame] : "선택 안 함"}</span>
      </p>
      <TextList title="결정" testId="slot-decisions" items={decisions} />
      <TextList title="시행한 치료" testId="slot-treatments" items={structure.treatments_given.map((t) => t.text)} />
      <TextList title="동의서" testId="slot-consents" items={structure.consents.map((t) => t.text)} />
      <TextList title="입원·병동" testId="slot-disposition" items={structure.disposition.map((t) => t.text)} />
      <TextList
        title="예후·연명의료"
        testId="slot-prognosis"
        items={structure.prognosis_and_goals.map((t) => t.text)}
      />
      <TextList title="환자·보호자 발화" testId="slot-family" items={family} />
      <TextList
        title="진찰·소견 기록 (용어 후보, 확인 불필요)"
        testId="slot-exam-terms"
        items={structure.term_candidates
          .filter((c) => c.risk === "exam")
          .map((c) => `"${c.spoken_text}" → ${c.term}`)}
      />

      {checklist.length > 0 && (
        <div className="notice-box" data-testid="review-checklist">
          <strong>의사 검수 체크리스트 ({checklist.filter((i) => checkedIds.has(i.id)).length}/{checklist.length})</strong>
          <p style={{ margin: "4px 0" }}>
            하지 않기로 한 결정, 조건부 결정, 추정 진단·시술 용어 후보는 원문과 대조해 확인한 뒤 체크하세요. 모두 체크해야 승인할 수 있습니다.
          </p>
          {checklist.map((item) => (
            <label key={item.id} style={{ display: "block" }}>
              <input
                type="checkbox"
                data-testid={`review-item-${item.id}`}
                checked={checkedIds.has(item.id)}
                disabled={readOnly}
                onChange={() => onToggle(item.id)}
              />{" "}
              {item.text}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
