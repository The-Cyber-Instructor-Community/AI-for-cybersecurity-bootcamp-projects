/**
 * FindingsTable — displays scored TLS findings from a scan.
 *
 * This is where the HNDL scoring becomes visible to the user.
 * Each finding shows:
 *   - Severity badge (color-coded: critical/high/medium/low)
 *   - The crypto primitive found (cipher suite, protocol, cert type)
 *   - HNDL risk score with formula breakdown (S × R × E = score)
 *   - Expandable row with NIST deadline, PQC replacement, and migration notes
 *
 * Findings arrive pre-sorted by HNDL risk (worst first) from the backend.
 */

import { useState } from "react";
import type { Scan, Finding, RemediationResponse } from "../types";
import type { LLMConfig } from "./LLMSettings";
import { requestRemediation } from "../services/api";
import SeverityChart from "./SeverityChart";
import ScanStats from "./ScanStats";
import "./FindingsTable.css";

interface FindingsTableProps {
  scan: Scan;
  llmConfig: LLMConfig;
}

// Filter options — "all" plus one per finding type
const FILTER_OPTIONS = [
  { key: "all", label: "All" },
  { key: "protocol", label: "Protocols" },
  { key: "cipher_suite", label: "Cipher Suites" },
  { key: "certificate", label: "Certificates" },
] as const;

type FilterKey = (typeof FILTER_OPTIONS)[number]["key"];

// Badge colors for each severity bucket
const SEVERITY_COLORS: Record<string, string> = {
  critical: "#ef4444",
  high: "#f97316",
  medium: "#eab308",
  low: "#22c55e",
};

// Human-readable finding type labels
const TYPE_LABELS: Record<string, string> = {
  protocol: "Protocol",
  cipher_suite: "Cipher Suite",
  certificate: "Certificate",
  key_exchange: "Key Exchange",
};

export default function FindingsTable({ scan, llmConfig }: FindingsTableProps) {
  // Track which finding rows are expanded to show remediation details
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());

  // Filter by finding type
  const [activeFilter, setActiveFilter] = useState<FilterKey>("all");

  // Toggle HNDL explainer visibility
  const [showExplainer, setShowExplainer] = useState(false);

  // AI deep dive state — keyed by finding ID
  const [remediations, setRemediations] = useState<Record<number, RemediationResponse>>({});
  const [loadingIds, setLoadingIds] = useState<Set<number>>(new Set());
  const [remediationErrors, setRemediationErrors] = useState<Record<number, string>>({});

  const toggleExpand = (id: number) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  // --- Handle AI deep dive request for a specific finding ---
  const handleDeepDive = async (findingId: number) => {
    // Mark as loading
    setLoadingIds((prev) => new Set(prev).add(findingId));
    // Clear any previous error for this finding
    setRemediationErrors((prev) => {
      const next = { ...prev };
      delete next[findingId];
      return next;
    });

    try {
      const result = await requestRemediation(scan.id, findingId, {
        provider: llmConfig.provider,
        api_key: llmConfig.apiKey,
        model: llmConfig.model,
      });
      // Store the remediation response
      setRemediations((prev) => ({ ...prev, [findingId]: result }));
    } catch (err: any) {
      const message =
        err.response?.data?.detail || err.message || "Remediation failed";
      setRemediationErrors((prev) => ({ ...prev, [findingId]: message }));
    } finally {
      setLoadingIds((prev) => {
        const next = new Set(prev);
        next.delete(findingId);
        return next;
      });
    }
  };

  if (scan.status === "failed") {
    return (
      <div className="findings-error">
        <h3>Scan Failed</h3>
        <p>{scan.error_message || "Unknown error"}</p>
      </div>
    );
  }

  if (scan.status === "running" || scan.status === "pending") {
    return (
      <div className="findings-loading">
        <div className="spinner" />
        <p>Scanning {scan.domain}...</p>
      </div>
    );
  }

  // Scan completed but found nothing — show a clean empty state
  if (scan.findings.length === 0) {
    return (
      <div className="findings-container">
        <div className="scan-header">
          <h2>{scan.domain}</h2>
          <div className="scan-meta">
            <span>0 findings</span>
            <span>
              {scan.completed_at
                ? new Date(scan.completed_at).toLocaleString()
                : ""}
            </span>
          </div>
        </div>
        <div className="empty-state" style={{ margin: "2rem" }}>
          <h2>No findings</h2>
          <p>
            No quantum-vulnerable cryptography was detected on {scan.domain}.
            This may mean the target has a very minimal TLS configuration or
            is already using PQC-ready settings.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="findings-container">
      {/* Scan summary header */}
      <div className="scan-header">
        <h2>{scan.domain}</h2>
        <div className="scan-meta">
          <span>{scan.findings.length} findings</span>
          <span>
            {scan.completed_at
              ? new Date(scan.completed_at).toLocaleString()
              : ""}
          </span>
        </div>
      </div>

      {/* HNDL model explainer — togglable "How is this scored?" panel */}
      <div className="explainer-section">
        <button
          className="explainer-toggle"
          aria-expanded={showExplainer}
          onClick={() => setShowExplainer(!showExplainer)}
        >
          {showExplainer ? "Hide" : "How is this scored?"}
        </button>

        {showExplainer && (
          <div className="explainer-content">
            <h3>The HNDL Risk Model</h3>
            <p>
              <strong>Harvest Now, Decrypt Later (HNDL)</strong> is a threat
              where adversaries record encrypted traffic today and wait for
              quantum computers to break the encryption. If your data is still
              sensitive when that happens, confidentiality is retroactively
              lost.
            </p>
            <p>Each finding is scored using three factors:</p>
            <div className="formula-display">
              <span className="formula-var s">S</span>
              <span className="formula-op">&times;</span>
              <span className="formula-var r">R</span>
              <span className="formula-op">&times;</span>
              <span className="formula-var e">E</span>
              <span className="formula-op">=</span>
              <span className="formula-result">HNDL Risk</span>
            </div>
            <div className="formula-legend">
              <div>
                <strong className="var-s">S — Data Sensitivity</strong> (1–5):
                How sensitive is the data flowing over this connection?
                <br />
                <em>You set this to {scan.data_sensitivity}</em>
              </div>
              <div>
                <strong className="var-r">R — Retention Horizon</strong> (1–5):
                How long must this data stay confidential?
                <br />
                <em>You set this to {scan.retention_horizon}</em>
              </div>
              <div>
                <strong className="var-e">E — Crypto Exposure</strong> (1–5):
                How soon does a quantum computer break this crypto?
                <br />
                <em>Auto-detected from the scan results</em>
              </div>
            </div>
            <div className="severity-scale">
              <h4>Severity Thresholds</h4>
              <div className="scale-items">
                <div className="scale-item">
                  <span className="scale-badge" style={{ background: "#ef4444" }}>Critical</span>
                  <span>76–125 — Sensitive long-retention data behind quantum-vulnerable crypto. Migrate immediately.</span>
                </div>
                <div className="scale-item">
                  <span className="scale-badge" style={{ background: "#f97316" }}>High</span>
                  <span>36–75 — Significant exposure on two or more axes. Plan migration within 1–2 years.</span>
                </div>
                <div className="scale-item">
                  <span className="scale-badge" style={{ background: "#eab308" }}>Medium</span>
                  <span>11–35 — Some risk but lower priority. Monitor and include in PQC roadmap.</span>
                </div>
                <div className="scale-item">
                  <span className="scale-badge" style={{ background: "#22c55e" }}>Low</span>
                  <span>1–10 — Minimal HNDL exposure. No urgent action needed.</span>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Donut chart — visual severity breakdown */}
      <SeverityChart findings={scan.findings} />

      {/* Key stats — at-a-glance risk summary */}
      <ScanStats findings={scan.findings} />

      {/* Filter tabs — narrow down by finding type */}
      <div className="filter-tabs">
        {FILTER_OPTIONS.map(({ key, label }) => {
          const count =
            key === "all"
              ? scan.findings.length
              : scan.findings.filter((f) => f.finding_type === key).length;
          return (
            <button
              key={key}
              className={`filter-tab ${activeFilter === key ? "active" : ""}`}
              onClick={() => setActiveFilter(key)}
            >
              {label} <span className="filter-count">{count}</span>
            </button>
          );
        })}
      </div>

      {/* Findings table — filtered by the active tab */}
      <div className="findings-table-wrapper">
        <table className="findings-table">
          <thead>
            <tr>
              <th>Severity</th>
              <th>Type</th>
              <th>Finding</th>
              <th>HNDL Risk</th>
            </tr>
          </thead>
          <tbody>
            {scan.findings
              .filter(
                (f) =>
                  activeFilter === "all" || f.finding_type === activeFilter
              )
              .map((finding) => (
                <FindingRow
                  key={finding.id}
                  finding={finding}
                  dataSensitivity={scan.data_sensitivity}
                  retentionHorizon={scan.retention_horizon}
                  isExpanded={expandedIds.has(finding.id)}
                  onToggle={() => toggleExpand(finding.id)}
                  onDeepDive={() => handleDeepDive(finding.id)}
                  remediation={remediations[finding.id] || null}
                  isLoadingRemediation={loadingIds.has(finding.id)}
                  remediationError={remediationErrors[finding.id] || null}
                  hasApiKey={llmConfig.provider === "ollama" || !!llmConfig.apiKey}
                />
              ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Individual finding row — click to expand remediation details
// ---------------------------------------------------------------------------

interface FindingRowProps {
  finding: Finding;
  dataSensitivity: number;
  retentionHorizon: number;
  isExpanded: boolean;
  onToggle: () => void;
  onDeepDive: () => void;
  remediation: RemediationResponse | null;
  isLoadingRemediation: boolean;
  remediationError: string | null;
  hasApiKey: boolean;
}

function FindingRow({
  finding,
  dataSensitivity,
  retentionHorizon,
  isExpanded,
  onToggle,
  onDeepDive,
  remediation,
  isLoadingRemediation,
  remediationError,
  hasApiKey,
}: FindingRowProps) {
  return (
    <>
      <tr className="finding-row" onClick={onToggle}>
        {/* Severity badge */}
        <td>
          <span
            className="severity-badge"
            style={{
              background: SEVERITY_COLORS[finding.severity_bucket] ?? "#6b7280",
            }}
          >
            {finding.severity_bucket}
          </span>
        </td>

        {/* Finding type */}
        <td className="finding-type">
          {TYPE_LABELS[finding.finding_type] || finding.finding_type}
        </td>

        {/* The actual crypto primitive */}
        <td className="finding-value">{finding.value}</td>

        {/* HNDL risk score with formula breakdown */}
        <td className="finding-score-cell">
          <span className="score-number">{finding.hndl_risk_score}</span>
          <span className="score-formula">
            <span className="formula-s">S{dataSensitivity}</span>
            {" × "}
            <span className="formula-r">R{retentionHorizon}</span>
            {" × "}
            <span className="formula-e">E{finding.crypto_exposure_score}</span>
          </span>
        </td>
      </tr>

      {/* Expanded remediation details */}
      {isExpanded && (
        <tr className="finding-details-row">
          <td colSpan={4}>
            <div className="finding-details">
              {/* Tier 1 — deterministic guidance from crypto_mappings */}
              {finding.nist_deadline && (
                <div className="detail-item">
                  <strong>NIST Deadline:</strong> {finding.nist_deadline}
                </div>
              )}
              {finding.pqc_replacement && (
                <div className="detail-item">
                  <strong>PQC Replacement:</strong> {finding.pqc_replacement}
                </div>
              )}
              {finding.migration_notes && (
                <div className="detail-item migration-notes">
                  <strong>Migration Guidance:</strong> {finding.migration_notes}
                </div>
              )}

              {/* Tier 2 — AI deep dive button and response */}
              <div className="deep-dive-section">
                {!remediation && !isLoadingRemediation && (
                  <button
                    className="deep-dive-btn"
                    disabled={!hasApiKey}
                    title={!hasApiKey ? "Configure an LLM provider in the sidebar first" : undefined}
                    onClick={(e) => {
                      e.stopPropagation();
                      onDeepDive();
                    }}
                  >
                    {hasApiKey
                      ? "AI Deep Dive — Get Detailed Remediation Plan"
                      : "AI Deep Dive — Configure LLM in sidebar first"}
                  </button>
                )}

                {/* Loading state */}
                {isLoadingRemediation && (
                  <div className="deep-dive-loading">
                    <div className="spinner-small" />
                    <span>Generating remediation plan...</span>
                  </div>
                )}

                {/* Error state */}
                {remediationError && (
                  <div className="deep-dive-error">
                    <strong>Remediation error:</strong> {remediationError}
                    <button
                      className="deep-dive-retry"
                      onClick={(e) => {
                        e.stopPropagation();
                        onDeepDive();
                      }}
                    >
                      Retry
                    </button>
                  </div>
                )}

                {/* Remediation response — structured AI output */}
                {remediation && (
                  <div className="deep-dive-response">
                    <div className="deep-dive-header">
                      <span className="deep-dive-title">AI Remediation Plan</span>
                      <span className="deep-dive-meta">
                        via {remediation.provider} ({remediation.model})
                      </span>
                    </div>

                    {remediation.summary && (
                      <div className="deep-dive-block">
                        <strong>Summary</strong>
                        <p>{remediation.summary}</p>
                      </div>
                    )}

                    {remediation.risk_explanation && (
                      <div className="deep-dive-block">
                        <strong>Risk Explanation</strong>
                        <p>{remediation.risk_explanation}</p>
                      </div>
                    )}

                    {remediation.migration_steps && (
                      <div className="deep-dive-block">
                        <strong>Migration Steps</strong>
                        <p className="deep-dive-steps">{remediation.migration_steps}</p>
                      </div>
                    )}

                    {remediation.priority && (
                      <div className="deep-dive-block">
                        <strong>Priority</strong>
                        <p>{remediation.priority}</p>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
