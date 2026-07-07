/**
 * SeverityChart — SVG donut chart showing the severity distribution.
 *
 * Pure SVG, no charting library. Uses stroke-dasharray/dashoffset
 * on circles to create the donut segments.
 */

import type { Finding } from "../types";
import "./SeverityChart.css";

interface SeverityChartProps {
  findings: Finding[];
}

// Colors + descriptions for each severity bucket
const SEVERITY_CONFIG = [
  { key: "critical", color: "#ef4444", label: "Critical", desc: "Migrate immediately" },
  { key: "high", color: "#f97316", label: "High", desc: "Plan migration soon" },
  { key: "medium", color: "#eab308", label: "Medium", desc: "Include in PQC roadmap" },
  { key: "low", color: "#22c55e", label: "Low", desc: "No urgent action" },
] as const;

// SVG circle geometry — larger for better visibility
const RADIUS = 70;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
const CENTER = 90;
const STROKE_WIDTH = 28;

export default function SeverityChart({ findings }: SeverityChartProps) {
  const total = findings.length;
  if (total === 0) return null;

  // Count findings per severity bucket
  const counts: Record<string, number> = {};
  for (const f of findings) {
    counts[f.severity_bucket] = (counts[f.severity_bucket] || 0) + 1;
  }

  // Build the donut segments
  let cumulativeOffset = 0;
  const segments = SEVERITY_CONFIG.map(({ key, color }) => {
    const count = counts[key] || 0;
    const fraction = count / total;
    const dashLength = fraction * CIRCUMFERENCE;
    const offset = -cumulativeOffset;
    cumulativeOffset += dashLength;
    return { key, color, count, dashLength, offset };
  }).filter((seg) => seg.count > 0);

  return (
    <div className="severity-chart">
      <svg viewBox={`0 0 ${CENTER * 2} ${CENTER * 2}`} className="donut-svg">
        {/* Background ring */}
        <circle
          cx={CENTER}
          cy={CENTER}
          r={RADIUS}
          fill="none"
          stroke="var(--border)"
          strokeWidth={STROKE_WIDTH}
        />

        {/* Severity segments */}
        {segments.map(({ key, color, dashLength, offset }) => (
          <circle
            key={key}
            cx={CENTER}
            cy={CENTER}
            r={RADIUS}
            fill="none"
            stroke={color}
            strokeWidth={STROKE_WIDTH}
            strokeDasharray={`${dashLength} ${CIRCUMFERENCE - dashLength}`}
            strokeDashoffset={offset}
            strokeLinecap="butt"
            transform={`rotate(-90 ${CENTER} ${CENTER})`}
            className="donut-segment"
          />
        ))}

        {/* Center text — total finding count */}
        <text x={CENTER} y={CENTER - 8} textAnchor="middle" className="donut-total">
          {total}
        </text>
        <text x={CENTER} y={CENTER + 16} textAnchor="middle" className="donut-label">
          findings
        </text>
      </svg>

      {/* Legend — with descriptions */}
      <div className="chart-legend">
        {SEVERITY_CONFIG.map(({ key, color, label, desc }) => (
          <div key={key} className="legend-item">
            <span className="legend-dot" style={{ background: color }} />
            <span className="legend-count">{counts[key] || 0}</span>
            <div className="legend-text">
              <span className="legend-label">{label}</span>
              <span className="legend-desc">{desc}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
