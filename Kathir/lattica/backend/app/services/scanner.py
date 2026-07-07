"""
sslyze Scanner Wrapper

Bridges sslyze's scan engine with Lattica's data model.
Takes a domain, runs a TLS scan, and returns structured findings
ready for HNDL scoring.

sslyze handles the hard part (TLS handshakes, cipher negotiation,
cert parsing). We just orchestrate the scan and extract the
crypto primitives we care about for quantum-risk assessment.
"""

import asyncio
import logging
from dataclasses import dataclass

from sslyze import (
    Scanner,
    ServerScanRequest,
    ServerNetworkLocation,
    ScanCommand,
)
from sslyze.errors import ServerHostnameCouldNotBeResolved

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures for parsed findings
# ---------------------------------------------------------------------------

@dataclass
class RawFinding:
    """
    A single crypto primitive found during a TLS scan.
    This is the intermediate format between sslyze's output
    and our database model. No scoring yet — that's the
    HNDL engine's job (Day 2).
    """
    finding_type: str   # "cipher_suite", "protocol", "certificate", "key_exchange"
    value: str          # The actual crypto primitive (e.g., "TLS_RSA_WITH_AES_256_GCM_SHA384")


# ---------------------------------------------------------------------------
# Main scanner function
# ---------------------------------------------------------------------------

async def scan_domain(domain: str) -> list[RawFinding]:
    """
    Run an sslyze TLS scan against a domain and return parsed findings.

    We run sslyze in a thread pool because it's synchronous and
    does blocking network I/O — we don't want it freezing the
    FastAPI event loop.

    Args:
        domain: Target domain (e.g., "example.com")

    Returns:
        List of RawFinding objects extracted from the scan

    Raises:
        ValueError: If the domain can't be resolved
        RuntimeError: If the scan fails for any reason
    """
    # Run the blocking sslyze scan in a background thread
    return await asyncio.to_thread(_run_sslyze_scan, domain)


def _run_sslyze_scan(domain: str) -> list[RawFinding]:
    """
    Synchronous sslyze scan — runs in a thread pool.
    This is where the actual TLS probing happens.
    """
    findings: list[RawFinding] = []

    # --- Step 1: Set up the scan target ---
    try:
        location = ServerNetworkLocation(hostname=domain)
    except Exception as e:
        raise ValueError(f"Invalid domain '{domain}': {e}")

    # --- Step 2: Configure what to scan ---
    # We care about cipher suites, protocols, and certificate info
    scan_request = ServerScanRequest(
        server_location=location,
        scan_commands={
            # Check which cipher suites are accepted for each TLS version
            ScanCommand.SSL_2_0_CIPHER_SUITES,
            ScanCommand.SSL_3_0_CIPHER_SUITES,
            ScanCommand.TLS_1_0_CIPHER_SUITES,
            ScanCommand.TLS_1_1_CIPHER_SUITES,
            ScanCommand.TLS_1_2_CIPHER_SUITES,
            ScanCommand.TLS_1_3_CIPHER_SUITES,
            # Certificate chain info (key type, size, signature algorithm)
            ScanCommand.CERTIFICATE_INFO,
        },
    )

    # --- Step 3: Run the scan ---
    scanner = Scanner()
    scanner.queue_scans([scan_request])

    # sslyze returns results as a generator — we only have one target
    for result in scanner.get_results():

        # Check if the connection itself failed
        if result.connectivity_error_trace:
            raise RuntimeError(
                f"Could not connect to {domain}: {result.connectivity_error_trace}"
            )

        # --- Step 4: Extract protocol findings ---
        # Each protocol version (SSL 2.0 through TLS 1.3) that the server accepts
        findings.extend(_extract_protocol_findings(result))

        # --- Step 5: Extract cipher suite findings ---
        # Individual cipher suites accepted within each protocol version
        findings.extend(_extract_cipher_findings(result))

        # --- Step 6: Extract certificate findings ---
        # Key type, key size, signature algorithm from the cert chain
        findings.extend(_extract_certificate_findings(result))

    logger.info(f"Scan of {domain} produced {len(findings)} findings")
    return findings


# ---------------------------------------------------------------------------
# Finding extractors — one per category
# ---------------------------------------------------------------------------

def _extract_protocol_findings(result) -> list[RawFinding]:
    """
    Check which TLS/SSL protocol versions the server accepts.
    Older protocols (SSL 2.0, SSL 3.0, TLS 1.0, TLS 1.1) are
    already deprecated — and all pre-TLS-1.3 protocols use
    key exchanges that are quantum-vulnerable.
    """
    findings = []

    # sslyze 6.x exposes results as direct attributes on scan_result,
    # each returning an "attempt" object with a .result property.
    # The attribute names are snake_case versions of the protocol.
    protocol_checks = [
        ("ssl_2_0_cipher_suites", "SSL 2.0"),
        ("ssl_3_0_cipher_suites", "SSL 3.0"),
        ("tls_1_0_cipher_suites", "TLS 1.0"),
        ("tls_1_1_cipher_suites", "TLS 1.1"),
        ("tls_1_2_cipher_suites", "TLS 1.2"),
        ("tls_1_3_cipher_suites", "TLS 1.3"),
    ]

    for attr_name, protocol_name in protocol_checks:
        try:
            attempt = getattr(result.scan_result, attr_name)
            # attempt.result is None if the scan command wasn't run
            if attempt.result and attempt.result.accepted_cipher_suites:
                findings.append(RawFinding(
                    finding_type="protocol",
                    value=protocol_name,
                ))
        except (AttributeError, Exception):
            # Scan command wasn't run or result not available
            continue

    return findings


def _extract_cipher_findings(result) -> list[RawFinding]:
    """
    Extract individual cipher suites the server accepts.
    Each cipher suite encodes the key exchange, authentication,
    encryption, and MAC algorithms — we need all of these to
    assess quantum vulnerability.

    Example: TLS_RSA_WITH_AES_256_GCM_SHA384
      - RSA key exchange → quantum-vulnerable
      - AES-256-GCM → quantum-safe (symmetric)
      - SHA384 → quantum-safe (hash)
    """
    findings = []
    seen_ciphers = set()  # Avoid duplicates across protocol versions

    # sslyze 6.x: access cipher results via direct attributes
    cipher_attrs = [
        "ssl_2_0_cipher_suites",
        "ssl_3_0_cipher_suites",
        "tls_1_0_cipher_suites",
        "tls_1_1_cipher_suites",
        "tls_1_2_cipher_suites",
        "tls_1_3_cipher_suites",
    ]

    for attr_name in cipher_attrs:
        try:
            attempt = getattr(result.scan_result, attr_name)
            if not attempt.result:
                continue
            for cipher in attempt.result.accepted_cipher_suites:
                cipher_name = cipher.cipher_suite.name

                # Skip if we already recorded this cipher from another protocol
                if cipher_name in seen_ciphers:
                    continue
                seen_ciphers.add(cipher_name)

                findings.append(RawFinding(
                    finding_type="cipher_suite",
                    value=cipher_name,
                ))
        except (AttributeError, Exception):
            continue

    return findings


def _extract_certificate_findings(result) -> list[RawFinding]:
    """
    Extract certificate chain details — key type, key size,
    and signature algorithm.

    The certificate's public key type determines quantum vulnerability:
      - RSA keys → broken by Shor's algorithm
      - ECDSA keys → broken by Shor's algorithm
      - Ed25519 → broken by Shor's algorithm (still ECC)

    The key SIZE matters for timeline — RSA-2048 lasts longer
    than RSA-1024 against classical attacks, but both fall
    equally fast to a quantum computer.
    """
    findings = []
    seen_certs = set()  # Deduplicate — cert chains often reuse key types and sig algos

    try:
        cert_attempt = result.scan_result.certificate_info
        if not cert_attempt.result:
            return findings
        cert_result = cert_attempt.result
    except (AttributeError, Exception):
        return findings

    for deployment in cert_result.certificate_deployments:
        # Walk the certificate chain (leaf cert + intermediates)
        for cert in deployment.received_certificate_chain:
            pub_key = cert.public_key()
            key_type = type(pub_key).__name__  # e.g., "_RSAPublicKey", "_EllipticCurvePublicKey"

            # Normalize the key type name for readability
            cert_value = None
            if "RSA" in key_type:
                cert_value = f"RSA-{pub_key.key_size}"
            elif "EllipticCurve" in key_type or "EC" in key_type:
                cert_value = f"ECDSA-{pub_key.key_size}"
            elif "Ed25519" in key_type:
                cert_value = "Ed25519"
            elif "Ed448" in key_type:
                cert_value = "Ed448"
            else:
                cert_value = f"Unknown ({key_type})"

            # Only add if we haven't seen this exact key type+size before
            if cert_value not in seen_certs:
                seen_certs.add(cert_value)
                findings.append(RawFinding(
                    finding_type="certificate",
                    value=cert_value,
                ))

            # Also capture the signature algorithm, deduplicated
            sig_algo = cert.signature_algorithm_oid._name if hasattr(cert.signature_algorithm_oid, '_name') else str(cert.signature_algorithm_oid.dotted_string)
            sig_value = f"Signature: {sig_algo}"
            if sig_value not in seen_certs:
                seen_certs.add(sig_value)
                findings.append(RawFinding(
                    finding_type="certificate",
                    value=sig_value,
                ))

    return findings
