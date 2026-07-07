/**
 * ScanStats — key metrics displayed as stat cards above the findings table.
 *
 * Shows at-a-glance risk summary:
 *   - Highest HNDL risk score found
 *   - Number of critical/high findings (the ones that need action)
 *   - Most urgent NIST deadline
 *   - Dominant finding type
 *
 * These stats give the user an instant sense of "how bad is it?"
 * before they dive into the individual findings.
 */

import type { Finding } from "../types";
import "./ScanStats.css";

interface ScanStatsProps {
  findings: Finding[];
}

export default function ScanStats({ findings }: ScanStatsProps) {
  if (findings.length === 0) return null;

  // --- Compute stats ---

  // Highest HNDL risk score
  const maxRisk = Math.max(...findings.map((f) => f.hndl_risk_score));

  // Count of urgent findings (critical + high)
  const urgentCount = findings.filter(
    (f) => f.severity_bucket === "critical" || f.severity_bucket === "high"
  ).length;

  // Most common finding type
  const typeCounts: Record<string, number> = {};
  for (const f of findings) {
    typeCounts[f.finding_type] = (typeCounts[f.finding_type] || 0) + 1;
  }
  const dominantType = Object.entries(typeCounts).sort(
    (a, b) => b[1] - a[1]
  )[0];

  const TYPE_LABELS: Record<string, string> = {
    protocol: "Protocols",
    cipher_suite: "Cipher Suites",
    certificate: "Certificates",
    key_exchange: "Key Exchanges",
  };

  // Determine overall risk level color
  const riskColor =
    maxRisk >= 76
      ? "#ef4444"
      : maxRisk >= 36
        ? "#f97316"
        : maxRisk >= 11
          ? "#eab308"
          : "#22c55e";

  return (
    <div className="scan-stats">
      {/* Peak risk score */}
      <div className="stat-card">
        <div className="stat-value" style={{ color: riskColor }}>
          {maxRisk}
        </div>
        <div className="stat-label">Peak HNDL Risk</div>
        <div className="stat-sublabel">out of 125</div>
      </div>

      {/* Urgent findings count */}
      <div className="stat-card">
        <div
          className="stat-value"
          style={{ color: urgentCount > 0 ? "#f97316" : "#22c55e" }}
        >
          {urgentCount}
        </div>
        <div className="stat-label">Urgent Findings</div>
        <div className="stat-sublabel">critical + high</div>
      </div>

      {/* Total findings */}
      <div className="stat-card">
        <div className="stat-value">{findings.length}</div>
        <div className="stat-label">Total Findings</div>
        <div className="stat-sublabel">across all types</div>
      </div>

      {/* Dominant finding type */}
      <div className="stat-card">
        <div className="stat-value">{dominantType[1]}</div>
        <div className="stat-label">
          {TYPE_LABELS[dominantType[0]] || dominantType[0]}
        </div>
        <div className="stat-sublabel">most common type</div>
      </div>
    </div>
  );
}
