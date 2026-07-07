/**
 * ScanForm — the entry point for running a TLS scan.
 *
 * Collects three inputs:
 *   1. Domain to scan (text input)
 *   2. Data Sensitivity (1–5 slider) — "How sensitive is this data?"
 *   3. Retention Horizon (1–5 slider) — "How long must it stay confidential?"
 *
 * The S and R values are what make Lattica a risk modeler, not just a scanner.
 * They inject human judgment into the HNDL scoring formula (S × R × E).
 */

import { useState } from "react";
import type { ScanCreate } from "../types";
import "./ScanForm.css";

// Human-readable labels for the 1–5 scales
const SENSITIVITY_LABELS: Record<number, string> = {
  1: "Public — no confidentiality needed",
  2: "Internal — low sensitivity",
  3: "Confidential — business data",
  4: "Restricted — PII, financial data",
  5: "Top Secret — health records, classified",
};

const RETENTION_LABELS: Record<number, string> = {
  1: "Ephemeral — hours to days",
  2: "Short-term — weeks to months",
  3: "Medium-term — 1–3 years",
  4: "Long-term — 3–7 years",
  5: "Regulatory — 7+ years (HIPAA, SOX, etc.)",
};

interface ScanFormProps {
  onSubmit: (payload: ScanCreate) => void;
  isLoading: boolean;
}

// Simple domain validation — allows subdomains, rejects empty and garbage input
const DOMAIN_RE = /^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$/;

export default function ScanForm({ onSubmit, isLoading }: ScanFormProps) {
  const [domain, setDomain] = useState("");
  const [sensitivity, setSensitivity] = useState(3);
  const [retention, setRetention] = useState(3);
  const [validationError, setValidationError] = useState<string | null>(null);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    // Auto-strip common user mistakes: "https://example.com/path" → "example.com"
    const cleaned = domain.trim()
      .replace(/^https?:\/\//, "")
      .replace(/\/.*$/, "")
      .replace(/:.*$/, "");

    if (!cleaned || !DOMAIN_RE.test(cleaned)) {
      setValidationError("Enter a plain domain like api.example.com");
      return;
    }

    setValidationError(null);
    onSubmit({
      domain: cleaned,
      data_sensitivity: sensitivity,
      retention_horizon: retention,
    });
  };

  return (
    <form className="scan-form" onSubmit={handleSubmit}>
      <h2>New TLS Scan</h2>

      {/* Domain input */}
      <div className="form-group">
        <label htmlFor="domain">Target Domain</label>
        <input
          id="domain"
          type="text"
          placeholder="e.g., api.example.com"
          value={domain}
          onChange={(e) => {
            setDomain(e.target.value);
            if (validationError) setValidationError(null);
          }}
          disabled={isLoading}
          autoFocus
        />
        {validationError && (
          <span className="validation-error">{validationError}</span>
        )}
      </div>

      {/* Data Sensitivity slider — the "S" in S×R×E */}
      <div className="form-group">
        <label htmlFor="sensitivity">
          Data Sensitivity: <strong>{sensitivity}</strong> —{" "}
          <span className="label-description">
            {SENSITIVITY_LABELS[sensitivity]}
          </span>
        </label>
        <input
          id="sensitivity"
          type="range"
          min={1}
          max={5}
          step={1}
          value={sensitivity}
          onChange={(e) => setSensitivity(Number(e.target.value))}
          disabled={isLoading}
          aria-valuetext={SENSITIVITY_LABELS[sensitivity]}
        />
        <div className="slider-range">
          <span>1 — Public</span>
          <span>5 — Top Secret</span>
        </div>
      </div>

      {/* Retention Horizon slider — the "R" in S×R×E */}
      <div className="form-group">
        <label htmlFor="retention">
          Retention Horizon: <strong>{retention}</strong> —{" "}
          <span className="label-description">
            {RETENTION_LABELS[retention]}
          </span>
        </label>
        <input
          id="retention"
          type="range"
          min={1}
          max={5}
          step={1}
          value={retention}
          onChange={(e) => setRetention(Number(e.target.value))}
          disabled={isLoading}
          aria-valuetext={RETENTION_LABELS[retention]}
        />
        <div className="slider-range">
          <span>1 — Ephemeral</span>
          <span>5 — Regulatory</span>
        </div>
      </div>

      {/* Submit */}
      <button type="submit" disabled={isLoading || !domain.trim()}>
        {isLoading ? "Scanning — this takes 5–15 s…" : "Scan"}
      </button>
    </form>
  );
}
