/**
 * Enum constants with Korean labels for admin edit forms.
 * These should match the backend enum values exactly.
 */

// ========================================
// User Status
// ========================================

export const USER_STATUS_OPTIONS = [
  { value: "draft", label: "상담 전" },
  { value: "pending_review", label: "상담 예정" },
  { value: "active", label: "상담 완료" },
  { value: "suspended", label: "정지" },
  { value: "withdrawn", label: "탈퇴" },
] as const;

// ========================================
// Gender
// ========================================

export const GENDER_OPTIONS = [
  { value: "male", label: "남성" },
  { value: "female", label: "여성" },
] as const;

// ========================================
// Education
// ========================================

export const EDUCATION_OPTIONS = [
  { value: "high_school", label: "고졸" },
  { value: "associate_enrolled", label: "전문대 재학" },
  { value: "associate_graduated", label: "전문대 졸업" },
  { value: "bachelor_enrolled", label: "학사 재학" },
  { value: "bachelor_graduated", label: "학사 졸업" },
  { value: "master_enrolled", label: "석사 재학" },
  { value: "master_graduated", label: "석사 졸업" },
  { value: "doctorate_enrolled", label: "박사 재학" },
  { value: "doctorate_graduated", label: "박사 졸업" },
  { value: "foreign", label: "해외 대학" },
  { value: "other", label: "기타" },
] as const;

// ========================================
// Salary Range
// ========================================

export const SALARY_RANGE_OPTIONS = [
  { value: "1", label: "1구간" },
  { value: "2", label: "2구간" },
  { value: "3", label: "3구간" },
  { value: "4", label: "4구간" },
  { value: "5", label: "5구간" },
] as const;

// ========================================
// Lifestyle - Smoking
// ========================================

export const SMOKING_OPTIONS = [
  { value: "non_smoker", label: "비흡연" },
  { value: "smoker", label: "흡연" },
  { value: "occasionally", label: "가끔 흡연" },
] as const;

// ========================================
// Lifestyle - Religion
// ========================================

export const RELIGION_OPTIONS = [
  { value: "none", label: "무교" },
  { value: "christian", label: "기독교" },
  { value: "buddhist", label: "불교" },
  { value: "catholic", label: "천주교" },
  { value: "other", label: "기타" },
] as const;

// ========================================
// Lifestyle - Tattoo
// ========================================

export const TATTOO_OPTIONS = [
  { value: "none", label: "문신 없음" },
  { value: "small", label: "작은 문신 있음" },
  { value: "visible", label: "눈에 띄는 문신" },
] as const;

// ========================================
// Lifestyle - Car Ownership
// ========================================

export const CAR_OWNERSHIP_OPTIONS = [
  { value: "yes", label: "있음" },
  { value: "no", label: "없음" },
  { value: "planning", label: "구입 계획 있음" },
] as const;

// ========================================
// Lifestyle - DINK Preference
// ========================================

export const DINK_PREFERENCE_OPTIONS = [
  { value: "yes", label: "딩크를 원합니다" },
  { value: "no", label: "딩크를 원하지 않습니다" },
  { value: "undecided", label: "아직 잘 모르겠어요" },
] as const;

// ========================================
// Lifestyle - Divorce Status
// ========================================

export const DIVORCE_STATUS_OPTIONS = [
  { value: "never_married", label: "돌싱이 아닙니다" },
  { value: "divorced", label: "돌싱입니다" },
  { value: "divorced_with_kids", label: "자녀있는 돌싱" },
] as const;

// ========================================
// Lifestyle - Long Distance
// ========================================

export const LONG_DISTANCE_OPTIONS = [
  { value: "impossible", label: "불가능" },
  { value: "depends", label: "상황에 따라" },
  { value: "possible", label: "가능" },
] as const;

// ========================================
// Document Verification Status
// ========================================

export const DOCUMENT_VERIFICATION_STATUS_OPTIONS = [
  { value: "pending", label: "검토 대기" },
  { value: "approved", label: "승인됨" },
  { value: "rejected", label: "반려됨" },
] as const;

// ========================================
// Helper functions
// ========================================

type EnumOption = { value: string; label: string };

/**
 * Get Korean label for an enum value
 */
export function getEnumLabel(
  options: readonly EnumOption[],
  value: string | null | undefined
): string {
  if (!value) return "-";
  const option = options.find((o) => o.value === value);
  return option?.label ?? value;
}

/**
 * Get label for user status
 */
export function getUserStatusLabel(value: string | null | undefined): string {
  return getEnumLabel(USER_STATUS_OPTIONS, value);
}

/**
 * Get label for gender
 */
export function getGenderLabel(value: string | null | undefined): string {
  return getEnumLabel(GENDER_OPTIONS, value);
}

/**
 * Get label for education
 */
export function getEducationLabel(value: string | null | undefined): string {
  return getEnumLabel(EDUCATION_OPTIONS, value);
}

/**
 * Get label for smoking
 */
export function getSmokingLabel(value: string | null | undefined): string {
  return getEnumLabel(SMOKING_OPTIONS, value);
}

/**
 * Get label for religion
 */
export function getReligionLabel(value: string | null | undefined): string {
  return getEnumLabel(RELIGION_OPTIONS, value);
}

/**
 * Get label for document verification status
 */
export function getDocumentStatusLabel(value: string | null | undefined): string {
  return getEnumLabel(DOCUMENT_VERIFICATION_STATUS_OPTIONS, value);
}
