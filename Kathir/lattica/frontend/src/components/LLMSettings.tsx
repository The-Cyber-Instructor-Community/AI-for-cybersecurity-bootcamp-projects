/**
 * LLMSettings — sidebar panel for configuring the AI remediation provider.
 *
 * Lets the user pick which LLM to use for deep dive remediation
 * and provide their API key. Settings are stored in App state
 * (not persisted — this is a demo tool, not a production system).
 *
 * Supported providers:
 *   - Gemini (free tier available — recommended)
 *   - OpenAI (requires API key with credits)
 *   - Claude (requires API key with credits)
 *   - Ollama (local, no key needed)
 */

import { useState } from "react";
import "./LLMSettings.css";

// Provider options with human-readable labels and descriptions
const PROVIDERS = [
  {
    value: "gemini",
    label: "Google Gemini",
    desc: "Free tier available",
    needsKey: true,
  },
  {
    value: "openai",
    label: "OpenAI",
    desc: "GPT-4o-mini default",
    needsKey: true,
  },
  {
    value: "claude",
    label: "Claude",
    desc: "Requires API credits",
    needsKey: true,
  },
  {
    value: "ollama",
    label: "Ollama",
    desc: "Local, no key needed",
    needsKey: false,
  },
] as const;

export interface LLMConfig {
  provider: string;
  apiKey: string;
  model: string;
}

interface LLMSettingsProps {
  config: LLMConfig;
  onChange: (config: LLMConfig) => void;
}

export default function LLMSettings({ config, onChange }: LLMSettingsProps) {
  // Collapsible — starts closed to keep the sidebar clean
  const [isOpen, setIsOpen] = useState(false);

  const currentProvider = PROVIDERS.find((p) => p.value === config.provider);

  return (
    <div className="llm-settings">
      {/* Toggle header */}
      <button
        className="llm-settings-toggle"
        onClick={() => setIsOpen(!isOpen)}
      >
        <span className="llm-settings-title">
          <span className="llm-icon">⚡</span>
          AI Remediation
        </span>
        <span className="llm-settings-status">
          {currentProvider?.label || "Not configured"}
        </span>
        <span className={`llm-chevron ${isOpen ? "open" : ""}`}>▸</span>
      </button>

      {/* Settings panel */}
      {isOpen && (
        <div className="llm-settings-body">
          {/* Provider selector */}
          <label className="llm-field">
            <span className="llm-field-label">Provider</span>
            <select
              value={config.provider}
              onChange={(e) =>
                onChange({ ...config, provider: e.target.value, model: "" })
              }
              className="llm-select"
            >
              {PROVIDERS.map(({ value, label, desc }) => (
                <option key={value} value={value}>
                  {label} — {desc}
                </option>
              ))}
            </select>
          </label>

          {/* API key input — only shown for providers that need it */}
          {currentProvider?.needsKey && (
            <label className="llm-field">
              <span className="llm-field-label">API Key</span>
              <input
                type="password"
                value={config.apiKey}
                onChange={(e) =>
                  onChange({ ...config, apiKey: e.target.value })
                }
                placeholder={`Enter ${currentProvider.label} API key`}
                className="llm-input"
              />
              <span className="llm-field-hint">
                {config.provider === "gemini"
                  ? "Free at aistudio.google.com"
                  : "Optional — falls back to server .env"}
              </span>
            </label>
          )}

          {/* Optional model override */}
          <label className="llm-field">
            <span className="llm-field-label">Model (optional)</span>
            <input
              type="text"
              value={config.model}
              onChange={(e) =>
                onChange({ ...config, model: e.target.value })
              }
              placeholder="Leave blank for default"
              className="llm-input"
            />
          </label>
        </div>
      )}
    </div>
  );
}
