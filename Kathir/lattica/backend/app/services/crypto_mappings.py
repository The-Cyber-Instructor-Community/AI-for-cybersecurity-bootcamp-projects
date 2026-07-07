"""
Crypto Exposure Mappings — the knowledge base behind HNDL scoring.

This module maps every crypto primitive we might encounter in a TLS scan
to three things:
  1. A quantum risk score (1–5) — how soon a quantum computer breaks it
  2. A NIST migration deadline — when it's deprecated / disallowed
  3. A PQC replacement — what to migrate to

These mappings are derived from:
  - NIST SP 800-131A Rev 2 (Transitioning Crypto Algorithms)
  - NIST IR 8547 (Transition to Post-Quantum Cryptography Standards)
  - CNSA 2.0 (NSA's Commercial National Security Algorithm Suite)
  - Google's 2029 PQC timeline announcement

Score scale:
  1 = PQC-ready or quantum-safe (symmetric ciphers, hashes)
  2 = Strong classical crypto, low quantum priority (large key ECC in PQC-hybrid)
  3 = Standard classical crypto, moderate quantum risk (RSA-4096, ECDHE-384)
  4 = Weakening classical crypto, high quantum risk (RSA-2048, ECDHE-256)
  5 = Already weak OR highest quantum priority (RSA-1024, DES, export ciphers)
"""

from dataclasses import dataclass


@dataclass
class CryptoProfile:
    """Everything we know about a crypto primitive's quantum risk."""
    exposure_score: int        # 1–5 quantum vulnerability score
    nist_deadline: str         # Human-readable NIST timeline
    pqc_replacement: str       # Recommended post-quantum replacement
    migration_notes: str       # Brief Tier 1 guidance


# ---------------------------------------------------------------------------
# Protocol version mappings
# ---------------------------------------------------------------------------
# Older protocols are scored higher because they ONLY support
# quantum-vulnerable key exchanges and have known classical weaknesses too.

PROTOCOL_MAP: dict[str, CryptoProfile] = {
    "SSL 2.0": CryptoProfile(
        exposure_score=5,
        nist_deadline="Already disallowed (since 2011)",
        pqc_replacement="TLS 1.3 with PQC key exchange (ML-KEM hybrid)",
        migration_notes="SSL 2.0 has critical vulnerabilities beyond quantum risk. "
                        "Disable immediately. No legitimate reason to keep this enabled.",
    ),
    "SSL 3.0": CryptoProfile(
        exposure_score=5,
        nist_deadline="Already disallowed (since 2015, POODLE)",
        pqc_replacement="TLS 1.3 with PQC key exchange (ML-KEM hybrid)",
        migration_notes="SSL 3.0 is broken by POODLE attack. Disable immediately. "
                        "All modern clients support TLS 1.2+.",
    ),
    "TLS 1.0": CryptoProfile(
        exposure_score=5,
        nist_deadline="Already deprecated (since 2020, PCI DSS / IETF RFC 8996)",
        pqc_replacement="TLS 1.3 with PQC key exchange (ML-KEM hybrid)",
        migration_notes="TLS 1.0 is deprecated by IETF and PCI DSS. Vulnerable to BEAST "
                        "and other attacks. All key exchanges in TLS 1.0 are quantum-vulnerable. "
                        "Disable and move to TLS 1.2 minimum, TLS 1.3 preferred.",
    ),
    "TLS 1.1": CryptoProfile(
        exposure_score=5,
        nist_deadline="Already deprecated (since 2020, IETF RFC 8996)",
        pqc_replacement="TLS 1.3 with PQC key exchange (ML-KEM hybrid)",
        migration_notes="TLS 1.1 is deprecated by IETF. No significant improvement over TLS 1.0 "
                        "for quantum resistance. Disable and move to TLS 1.2 minimum, TLS 1.3 preferred.",
    ),
    "TLS 1.2": CryptoProfile(
        exposure_score=3,
        nist_deadline="Deprecated 2030 (CNSA 2.0), evaluate PQC hybrid by 2027",
        pqc_replacement="TLS 1.3 with ML-KEM-768 hybrid key exchange",
        migration_notes="TLS 1.2 is still widely used and currently acceptable. However, its key "
                        "exchanges (RSA, ECDHE) are quantum-vulnerable. Plan migration to TLS 1.3 "
                        "with PQC hybrid key exchange. Priority depends on cipher suites in use — "
                        "ECDHE suites are better than static RSA for forward secrecy.",
    ),
    "TLS 1.3": CryptoProfile(
        exposure_score=2,
        nist_deadline="Current standard; PQC hybrid extensions expected by 2028",
        pqc_replacement="TLS 1.3 with ML-KEM-768 hybrid (draft-ietf-tls-hybrid-design)",
        migration_notes="TLS 1.3 is the best available today. It mandates forward secrecy (no static "
                        "RSA key exchange) and uses strong AEAD ciphers. However, the ECDHE key exchange "
                        "is still quantum-vulnerable. Adopt PQC hybrid key exchange (ML-KEM + X25519) "
                        "when your TLS library supports it. Chrome and Firefox already support X25519Kyber768.",
    ),
}


# ---------------------------------------------------------------------------
# Cipher suite mappings
# ---------------------------------------------------------------------------
# Cipher suites encode: key_exchange + authentication + encryption + MAC
# We score primarily on the KEY EXCHANGE since that's what quantum breaks.
#
# Naming convention:
#   TLS_RSA_WITH_*          → RSA key exchange (no forward secrecy, quantum-vulnerable)
#   TLS_ECDHE_RSA_WITH_*    → ECDHE key exchange, RSA auth (forward secrecy, quantum-vulnerable)
#   TLS_ECDHE_ECDSA_WITH_*  → ECDHE key exchange, ECDSA auth (forward secrecy, quantum-vulnerable)
#   TLS_AES_*               → TLS 1.3 suite (ECDHE implied, quantum-vulnerable key exchange)
#   TLS_CHACHA20_*          → TLS 1.3 suite (ECDHE implied, quantum-vulnerable key exchange)

def _classify_cipher_suite(cipher_name: str) -> CryptoProfile:
    """
    Classify a cipher suite by its quantum risk based on the key exchange.

    The key insight: symmetric ciphers (AES, ChaCha20) and hash functions
    (SHA-256, SHA-384) are quantum-RESISTANT (Grover's algorithm only halves
    their effective strength). The vulnerability is in the KEY EXCHANGE
    (RSA, ECDHE) — that's what Shor's algorithm breaks.
    """

    name = cipher_name.upper()

    # --- TLS 1.3 suites (no explicit key exchange in name) ---
    # TLS 1.3 mandates ECDHE, which is quantum-vulnerable, but at least
    # provides forward secrecy. Scored lower risk than static RSA.
    if name.startswith("TLS_AES_") or name.startswith("TLS_CHACHA20_"):
        return CryptoProfile(
            exposure_score=2,
            nist_deadline="PQC hybrid key exchange recommended by 2028",
            pqc_replacement="Same cipher with ML-KEM-768 hybrid key exchange",
            migration_notes="TLS 1.3 cipher with strong symmetric encryption. The underlying "
                            "ECDHE key exchange is quantum-vulnerable but provides forward secrecy. "
                            "Adopt hybrid PQC key exchange (X25519+ML-KEM-768) when available.",
        )

    # --- Static RSA key exchange (worst case) ---
    # No forward secrecy: if the server's RSA key is ever broken (including
    # by a future quantum computer), ALL past traffic is decryptable.
    # This is the #1 HNDL risk.
    if name.startswith("TLS_RSA_WITH_"):
        # Check for especially weak ciphers
        if "3DES" in name or "DES" in name:
            return CryptoProfile(
                exposure_score=5,
                nist_deadline="Already disallowed (3DES deprecated 2023, NIST SP 800-131A)",
                pqc_replacement="TLS 1.3 with AES-256-GCM + ML-KEM-768 hybrid key exchange",
                migration_notes="CRITICAL: Static RSA key exchange with 3DES. No forward secrecy — "
                                "all past recorded traffic is decryptable once the RSA key is broken "
                                "by a quantum computer. 3DES is also classically weak (64-bit block, "
                                "Sweet32 attack). Disable this cipher suite immediately.",
            )
        if "RC4" in name:
            return CryptoProfile(
                exposure_score=5,
                nist_deadline="Already disallowed (RC4 prohibited by RFC 7465)",
                pqc_replacement="TLS 1.3 with AES-256-GCM + ML-KEM-768 hybrid key exchange",
                migration_notes="CRITICAL: RC4 is broken classically and the RSA key exchange "
                                "has no forward secrecy. Disable immediately.",
            )
        if "NULL" in name or "EXPORT" in name:
            return CryptoProfile(
                exposure_score=5,
                nist_deadline="Already disallowed",
                pqc_replacement="TLS 1.3 with AES-256-GCM + ML-KEM-768 hybrid key exchange",
                migration_notes="CRITICAL: NULL/EXPORT cipher provides no real encryption. "
                                "Disable immediately.",
            )
        # Standard RSA key exchange with AES
        return CryptoProfile(
            exposure_score=4,
            nist_deadline="Deprecated 2030, disallowed 2035 (NIST IR 8547)",
            pqc_replacement="TLS_ECDHE_RSA or migrate to TLS 1.3 with ML-KEM-768 hybrid",
            migration_notes="Static RSA key exchange — no forward secrecy. If the server's private "
                            "key is ever compromised (classically or by quantum), all recorded past "
                            "sessions are decryptable. This is the highest HNDL risk category. "
                            "Migrate to ECDHE-based suites immediately, then to PQC hybrid.",
        )

    # --- ECDHE key exchange (better, but still quantum-vulnerable) ---
    # Forward secrecy means each session uses a unique ephemeral key.
    # A quantum computer can still break each session individually, but
    # the attacker needs to break EVERY session separately rather than
    # just cracking one long-term key.
    if "ECDHE" in name:
        if "3DES" in name or "RC4" in name:
            return CryptoProfile(
                exposure_score=4,
                nist_deadline="Already disallowed (weak symmetric cipher)",
                pqc_replacement="TLS 1.3 with AES-256-GCM + ML-KEM-768 hybrid",
                migration_notes="ECDHE provides forward secrecy but the symmetric cipher (3DES/RC4) "
                                "is classically broken. Disable this suite. The ECDHE key exchange "
                                "itself is also quantum-vulnerable.",
            )
        return CryptoProfile(
            exposure_score=3,
            nist_deadline="Deprecated 2030, disallowed 2035 (NIST IR 8547 / CNSA 2.0)",
            pqc_replacement="TLS 1.3 with ML-KEM-768 hybrid key exchange (X25519+ML-KEM)",
            migration_notes="ECDHE provides forward secrecy, which limits HNDL exposure — each "
                            "session must be broken individually. However, ECDHE is still quantum-"
                            "vulnerable (Shor's algorithm on elliptic curves). Plan migration to "
                            "hybrid PQC key exchange by 2028.",
        )

    # --- DHE key exchange (rare these days, but possible) ---
    if "DHE" in name and "ECDHE" not in name:
        return CryptoProfile(
            exposure_score=4,
            nist_deadline="Deprecated 2030 (NIST IR 8547)",
            pqc_replacement="TLS 1.3 with ML-KEM-768 hybrid key exchange",
            migration_notes="DHE provides forward secrecy but is quantum-vulnerable (Shor's "
                            "algorithm on discrete logarithms). Also often configured with weak "
                            "DH parameters. Migrate to TLS 1.3 with PQC hybrid key exchange.",
        )

    # --- Fallback for unrecognized suites ---
    return CryptoProfile(
        exposure_score=3,
        nist_deadline="Review manually — unrecognized cipher suite",
        pqc_replacement="Migrate to TLS 1.3 with ML-KEM-768 hybrid key exchange",
        migration_notes=f"Unrecognized cipher suite: {cipher_name}. Review manually for "
                        "quantum-vulnerable key exchange components.",
    )


# Cache for cipher suite lookups (avoid re-classifying the same suite)
_cipher_cache: dict[str, CryptoProfile] = {}


def get_cipher_profile(cipher_name: str) -> CryptoProfile:
    """Look up or classify a cipher suite's quantum risk profile."""
    if cipher_name not in _cipher_cache:
        _cipher_cache[cipher_name] = _classify_cipher_suite(cipher_name)
    return _cipher_cache[cipher_name]


# ---------------------------------------------------------------------------
# Certificate / key type mappings
# ---------------------------------------------------------------------------
# Certificate keys are vulnerable to Shor's algorithm regardless of size.
# Key size affects classical security timeline but NOT quantum timeline —
# a quantum computer breaks RSA-2048 and RSA-4096 with roughly the same
# effort (both need ~4000 logical qubits for Shor's).

CERTIFICATE_MAP: dict[str, CryptoProfile] = {
    # RSA keys — all quantum-vulnerable via Shor's algorithm
    "RSA-1024": CryptoProfile(
        exposure_score=5,
        nist_deadline="Already disallowed (classically weak since 2013)",
        pqc_replacement="ML-DSA-65 (FIPS 204) or SLH-DSA (FIPS 205)",
        migration_notes="RSA-1024 is broken classically AND quantum-vulnerable. Replace immediately "
                        "with at least RSA-2048 (short term) or ML-DSA-65 (long term PQC).",
    ),
    "RSA-2048": CryptoProfile(
        exposure_score=4,
        nist_deadline="Deprecated 2030, disallowed 2035 (NIST IR 8547)",
        pqc_replacement="ML-DSA-65 (FIPS 204) for signing, ML-KEM-768 (FIPS 203) for key exchange",
        migration_notes="RSA-2048 is classically secure for now but quantum-vulnerable. Shor's "
                        "algorithm breaks all RSA key sizes with roughly equal effort. Plan migration "
                        "to ML-DSA (CRYSTALS-Dilithium) for signatures by 2030.",
    ),
    "RSA-3072": CryptoProfile(
        exposure_score=4,
        nist_deadline="Deprecated 2030, disallowed 2035 (NIST IR 8547)",
        pqc_replacement="ML-DSA-65 (FIPS 204)",
        migration_notes="RSA-3072 provides ~128-bit classical security but is equally vulnerable "
                        "to quantum attack as RSA-2048. Migrate to ML-DSA for signatures.",
    ),
    "RSA-4096": CryptoProfile(
        exposure_score=3,
        nist_deadline="Deprecated 2030, disallowed 2035 (NIST IR 8547)",
        pqc_replacement="ML-DSA-87 (FIPS 204)",
        migration_notes="RSA-4096 has the strongest classical security of the RSA family but is "
                        "still quantum-vulnerable. Slightly lower priority than RSA-2048 only because "
                        "it's more likely used in root/intermediate CAs with shorter effective lifetimes. "
                        "Plan PQC migration to ML-DSA.",
    ),
    # ECDSA keys — quantum-vulnerable via Shor's on elliptic curves
    "ECDSA-256": CryptoProfile(
        exposure_score=4,
        nist_deadline="Deprecated 2030, disallowed 2035 (NIST IR 8547 / CNSA 2.0)",
        pqc_replacement="ML-DSA-44 (FIPS 204) or hybrid ECDSA-256 + ML-DSA-44",
        migration_notes="ECDSA P-256 provides ~128-bit classical security but is quantum-vulnerable. "
                        "Shor's algorithm on elliptic curves is actually more efficient than on RSA. "
                        "Migrate to ML-DSA (CRYSTALS-Dilithium) for certificate signatures.",
    ),
    "ECDSA-384": CryptoProfile(
        exposure_score=3,
        nist_deadline="Deprecated 2030, disallowed 2035 (CNSA 2.0)",
        pqc_replacement="ML-DSA-65 (FIPS 204)",
        migration_notes="ECDSA P-384 provides ~192-bit classical security. Quantum-vulnerable but "
                        "slightly lower priority than P-256 due to higher classical strength. "
                        "Migrate to ML-DSA-65 for signatures.",
    ),
    "ECDSA-521": CryptoProfile(
        exposure_score=3,
        nist_deadline="Deprecated 2030, disallowed 2035 (CNSA 2.0)",
        pqc_replacement="ML-DSA-87 (FIPS 204)",
        migration_notes="ECDSA P-521 has the strongest classical ECC security (~256-bit) but is "
                        "equally quantum-vulnerable as smaller curves. Migrate to ML-DSA-87.",
    ),
    # EdDSA keys — also quantum-vulnerable (still elliptic curve based)
    "Ed25519": CryptoProfile(
        exposure_score=4,
        nist_deadline="Deprecated 2030, disallowed 2035 (NIST IR 8547)",
        pqc_replacement="ML-DSA-44 (FIPS 204) or SLH-DSA-SHA2-128s (FIPS 205)",
        migration_notes="Ed25519 (Curve25519) is quantum-vulnerable via Shor's algorithm on "
                        "elliptic curves. It's excellent classically but provides no quantum resistance. "
                        "Migrate to ML-DSA or SLH-DSA for post-quantum signatures.",
    ),
    "Ed448": CryptoProfile(
        exposure_score=3,
        nist_deadline="Deprecated 2030, disallowed 2035 (NIST IR 8547)",
        pqc_replacement="ML-DSA-65 (FIPS 204)",
        migration_notes="Ed448 provides ~224-bit classical security. Quantum-vulnerable but slightly "
                        "lower priority. Migrate to ML-DSA-65.",
    ),
}


# ---------------------------------------------------------------------------
# Signature algorithm mappings
# ---------------------------------------------------------------------------
# These appear in certificate findings as "Signature: sha256WithRSAEncryption" etc.

SIGNATURE_MAP: dict[str, CryptoProfile] = {
    "sha256WithRSAEncryption": CryptoProfile(
        exposure_score=4,
        nist_deadline="Deprecated 2030, disallowed 2035 (NIST IR 8547)",
        pqc_replacement="ML-DSA-65 (FIPS 204)",
        migration_notes="RSA-based signature. SHA-256 hash is quantum-safe (Grover only halves "
                        "strength to ~128-bit), but the RSA signing key is quantum-vulnerable. "
                        "Migrate certificate signing to ML-DSA.",
    ),
    "sha384WithRSAEncryption": CryptoProfile(
        exposure_score=4,
        nist_deadline="Deprecated 2030, disallowed 2035 (NIST IR 8547)",
        pqc_replacement="ML-DSA-65 (FIPS 204)",
        migration_notes="RSA-based signature with SHA-384. Same quantum risk as SHA-256 variant — "
                        "the RSA key is the vulnerable component, not the hash.",
    ),
    "sha512WithRSAEncryption": CryptoProfile(
        exposure_score=4,
        nist_deadline="Deprecated 2030, disallowed 2035 (NIST IR 8547)",
        pqc_replacement="ML-DSA-87 (FIPS 204)",
        migration_notes="RSA-based signature with SHA-512. RSA key is quantum-vulnerable regardless "
                        "of hash strength.",
    ),
    "sha1WithRSAEncryption": CryptoProfile(
        exposure_score=5,
        nist_deadline="Already disallowed (SHA-1 deprecated since 2011, broken 2017)",
        pqc_replacement="ML-DSA-65 (FIPS 204)",
        migration_notes="CRITICAL: SHA-1 is classically broken (collision attacks demonstrated). "
                        "The RSA key is also quantum-vulnerable. Replace immediately.",
    ),
    "ecdsa-with-SHA256": CryptoProfile(
        exposure_score=4,
        nist_deadline="Deprecated 2030, disallowed 2035 (CNSA 2.0)",
        pqc_replacement="ML-DSA-44 (FIPS 204)",
        migration_notes="ECDSA signature with SHA-256. The ECDSA key is quantum-vulnerable. "
                        "Migrate to ML-DSA for post-quantum certificate signatures.",
    ),
    "ecdsa-with-SHA384": CryptoProfile(
        exposure_score=3,
        nist_deadline="Deprecated 2030, disallowed 2035 (CNSA 2.0)",
        pqc_replacement="ML-DSA-65 (FIPS 204)",
        migration_notes="ECDSA signature with SHA-384. Quantum-vulnerable via the ECDSA key.",
    ),
}


# ---------------------------------------------------------------------------
# Lookup function — single entry point for scoring
# ---------------------------------------------------------------------------

def get_crypto_profile(finding_type: str, value: str) -> CryptoProfile:
    """
    Look up the quantum risk profile for any finding.

    This is the main entry point used by the HNDL scoring engine.
    Routes to the appropriate mapping based on finding type.

    Args:
        finding_type: One of "protocol", "cipher_suite", "certificate"
        value: The finding value (e.g., "TLS 1.2", "TLS_RSA_WITH_AES_256_GCM_SHA384", "RSA-2048")

    Returns:
        CryptoProfile with exposure score, NIST deadline, PQC replacement, and migration notes
    """
    if finding_type == "protocol":
        return PROTOCOL_MAP.get(value, CryptoProfile(
            exposure_score=3,
            nist_deadline="Unknown protocol — review manually",
            pqc_replacement="Migrate to TLS 1.3 with PQC hybrid key exchange",
            migration_notes=f"Unrecognized protocol: {value}. Review for quantum vulnerability.",
        ))

    if finding_type == "cipher_suite":
        return get_cipher_profile(value)

    if finding_type == "certificate":
        # Certificate findings can be key types ("RSA-2048") or signatures ("Signature: sha256...")
        if value.startswith("Signature: "):
            sig_algo = value.replace("Signature: ", "")
            return SIGNATURE_MAP.get(sig_algo, CryptoProfile(
                exposure_score=3,
                nist_deadline="Review manually — unrecognized signature algorithm",
                pqc_replacement="ML-DSA-65 (FIPS 204)",
                migration_notes=f"Unrecognized signature algorithm: {sig_algo}. "
                                "Most signature algorithms in use today are quantum-vulnerable.",
            ))
        else:
            return CERTIFICATE_MAP.get(value, CryptoProfile(
                exposure_score=3,
                nist_deadline="Review manually — unrecognized key type",
                pqc_replacement="ML-DSA-65 (FIPS 204) or ML-KEM-768 (FIPS 203)",
                migration_notes=f"Unrecognized key type: {value}. Review for quantum vulnerability.",
            ))

    # Fallback for any unknown finding type
    return CryptoProfile(
        exposure_score=3,
        nist_deadline="Review manually",
        pqc_replacement="Consult NIST PQC standards (FIPS 203, 204, 205)",
        migration_notes=f"Unknown finding type '{finding_type}' with value '{value}'.",
    )
