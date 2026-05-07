export const APP_NAME = "Orbit";

export const LOCAL_STORAGE_KEYS = {
  draftRawText: "orbit:draft-raw-text",
  draftExtraction: "orbit:draft-extraction",
  pendingCommit: "orbit:pending-commit",
  anonymousId: "orbit:anonymous-id",
} as const;

export const DEFAULT_FOLLOW_UP_DAYS = 21;
export const EXTRACTION_MODEL = "gpt-4o-mini";
export const EMBEDDING_MODEL = "text-embedding-3-small";
