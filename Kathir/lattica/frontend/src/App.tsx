/**
 * App — main layout for Lattica.
 *
 * Two-column layout:
 *   Left sidebar:  Scan form + scan history
 *   Main area:     Findings table for the selected scan
 *
 * State management is kept simple — useState at the App level.
 * No Redux, no context providers. For a 7-day capstone, prop
 * drilling through 2 levels is fine.
 */

import { useState, useEffect, useCallback } from "react";
import ScanForm from "./components/ScanForm";
import FindingsTable from "./components/FindingsTable";
import ScanHistory from "./components/ScanHistory";
import LLMSettings from "./components/LLMSettings";
import type { LLMConfig } from "./components/LLMSettings";
import { createScan, listScans, getScan } from "./services/api";
import type { Scan, ScanCreate, ScanSummary } from "./types";
import "./App.css";

export default function App() {
  // The scan currently displayed in the main area
  const [activeScan, setActiveScan] = useState<Scan | null>(null);

  // List of all past scans (sidebar)
  const [scanList, setScanList] = useState<ScanSummary[]>([]);

  // Loading state for the scan form
  const [isScanning, setIsScanning] = useState(false);

  // Error state
  const [error, setError] = useState<string | null>(null);

  // LLM provider config for AI remediation (stored in state, not persisted)
  const [llmConfig, setLlmConfig] = useState<LLMConfig>({
    provider: "gemini",
    apiKey: "",
    model: "",
  });

  // Load scan history on mount
  useEffect(() => {
    listScans()
      .then(setScanList)
      .catch(() => {
        /* Backend might not be running yet — that's fine */
      });
  }, []);

  // --- Handle new scan submission ---
  const handleScan = useCallback(async (payload: ScanCreate) => {
    setIsScanning(true);
    setError(null);

    try {
      // This blocks until sslyze finishes (typically 3–15 seconds)
      const result = await createScan(payload);
      setActiveScan(result);

      // Refresh the scan history list
      const updatedList = await listScans();
      setScanList(updatedList);
    } catch (err: any) {
      const message =
        err.response?.data?.detail || err.message || "Scan failed";
      setError(message);
    } finally {
      setIsScanning(false);
    }
  }, []);

  // --- Handle clicking a past scan in the history ---
  const handleSelectScan = useCallback(async (scanId: number) => {
    try {
      const result = await getScan(scanId);
      setActiveScan(result);
      setError(null);
    } catch {
      setActiveScan(null);
      setError("Failed to load scan results");
    }
  }, []);

  return (
    <div className="app">
      {/* Header */}
      <header className="app-header">
        <h1>Lattica</h1>
        <span className="app-subtitle">
          Post-Quantum Cryptography Readiness
        </span>
      </header>

      {/* Main layout */}
      <div className="app-layout">
        {/* Left sidebar — form + history */}
        <aside className="sidebar">
          <ScanForm onSubmit={handleScan} isLoading={isScanning} />
          <LLMSettings config={llmConfig} onChange={setLlmConfig} />
          <ScanHistory
            scans={scanList}
            activeScanId={activeScan?.id ?? null}
            onSelect={handleSelectScan}
          />
        </aside>

        {/* Main content area — findings */}
        <main className="main-content">
          {error && (
            <div className="error-banner">
              <p>{error}</p>
              <button onClick={() => setError(null)}>Dismiss</button>
            </div>
          )}

          {activeScan ? (
            <FindingsTable scan={activeScan} llmConfig={llmConfig} />
          ) : (
            <div className="empty-state">
              <h2>No scan selected</h2>
              <p>
                Enter a domain and configure the HNDL risk parameters to run
                your first scan, or select a previous scan from the history.
              </p>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
