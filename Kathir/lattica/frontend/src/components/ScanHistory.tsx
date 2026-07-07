/**
 * ScanHistory — lists previous scans so users can revisit results.
 *
 * Shows domain, status, and timestamp for each past scan.
 * Clicking a scan loads its full results into the FindingsTable.
 */

import type { ScanSummary } from "../types";
import "./ScanHistory.css";

interface ScanHistoryProps {
  scans: ScanSummary[];
  activeScanId: number | null;
  onSelect: (scanId: number) => void;
}

// Status indicator colors
const STATUS_COLORS: Record<string, string> = {
  completed: "#22c55e",
  running: "#3b82f6",
  pending: "#eab308",
  failed: "#ef4444",
};

export default function ScanHistory({
  scans,
  activeScanId,
  onSelect,
}: ScanHistoryProps) {
  if (scans.length === 0) {
    return (
      <div className="scan-history empty">
        <h3>Scan History</h3>
        <p>No scans yet. Run your first scan above.</p>
      </div>
    );
  }

  return (
    <div className="scan-history">
      <h3>Scan History</h3>
      <ul className="scan-list">
        {scans.map((scan) => (
          <li
            key={scan.id}
            className={`scan-item ${scan.id === activeScanId ? "active" : ""} ${scan.status !== "completed" ? "non-selectable" : ""}`}
            onClick={() => scan.status === "completed" && onSelect(scan.id)}
          >
            {/* Status dot */}
            <span
              className="status-dot"
              style={{ background: STATUS_COLORS[scan.status] || "#6b7280" }}
              title={scan.status}
            />

            {/* Scan info */}
            <div className="scan-info">
              <span className="scan-domain">{scan.domain}</span>
              <span className="scan-date">
                {new Date(scan.created_at).toLocaleDateString()}{" "}
                {new Date(scan.created_at).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
            </div>

            {/* S and R values */}
            <span className="scan-params">
              S{scan.data_sensitivity} R{scan.retention_horizon}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
