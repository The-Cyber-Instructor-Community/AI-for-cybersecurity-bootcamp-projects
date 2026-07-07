/**
 * TypeScript types for Lattica's API responses.
 * These mirror the Pydantic schemas on the backend.
 */

// --- Scan types ---

export interface ScanCreate {
  domain: string;
  data_sensitivity: number; // 1–5
  retention_horizon: number; // 1–5
}

export interface Finding {
  id: number;
  finding_type: "protocol" | "cipher_suite" | "certificate" | "key_exchange";
  value: string;
  crypto_exposure_score: number; // 1–5
  hndl_risk_score: number; // 1–125
  severity_bucket: "critical" | "high" | "medium" | "low";
  nist_deadline: string | null;
  pqc_replacement: string | null;
  migration_notes: string | null;
}

export interface Scan {
  id: number;
  domain: string;
  data_sensitivity: number;
  retention_horizon: number;
  status: "pending" | "running" | "completed" | "failed";
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
  findings: Finding[];
}

export interface ScanSummary {
  id: number;
  domain: string;
  status: string;
  data_sensitivity: number;
  retention_horizon: number;
  created_at: string;
  completed_at: string | null;
}

// --- Remediation types (AI deep dive) ---

export interface RemediationRequest {
  provider: string;  // "gemini", "openai", "claude", "ollama"
  api_key: string;   // User-provided key (optional, falls back to server .env)
  model: string;     // Optional model override
}

export interface RemediationResponse {
  summary: string;           // 1–2 sentence executive summary
  risk_explanation: string;  // Why this finding matters for HNDL
  migration_steps: string;   // Step-by-step migration plan
  priority: string;          // Recommended priority and timeline
  provider: string;          // Which LLM generated this
  model: string;             // Specific model used
}
