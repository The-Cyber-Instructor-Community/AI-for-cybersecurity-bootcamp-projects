"""
DNS recon tool — passive/active DNS enumeration using dnspython.
Covers: reverse PTR, A/AAAA, MX, NS, TXT records, zone transfer attempt,
and common subdomain brute-force when a domain is given.
"""
import socket
import re

try:
    import dns.resolver
    import dns.reversename
    import dns.zone
    import dns.query
    HAS_DNSPYTHON = True
except ImportError:
    HAS_DNSPYTHON = False

COMMON_SUBDOMAINS = [
    "www", "mail", "ftp", "vpn", "admin", "dev", "staging", "api",
    "ns1", "ns2", "smtp", "pop", "imap", "webmail", "remote", "ssh",
]


def run_dns_recon(target: str) -> dict:
    """
    Perform DNS reconnaissance on an IP or domain.

    Args:
        target: IP address or domain name

    Returns:
        dict with keys: target, is_ip, reverse_dns, records,
                        subdomains, zone_transfer, error
    """
    if not HAS_DNSPYTHON:
        return {"error": "dnspython not installed — run: pip install dnspython"}

    is_ip = bool(re.match(r"^\d+\.\d+\.\d+\.\d+$", target))
    results = {
        "target":       target,
        "is_ip":        is_ip,
        "reverse_dns":  "",
        "records":      {},
        "subdomains":   [],
        "zone_transfer": [],
        "error":        None,
    }

    resolver = dns.resolver.Resolver()
    resolver.timeout  = 5
    resolver.lifetime = 10

    if is_ip:
        # Reverse PTR lookup
        results["reverse_dns"] = _reverse_lookup(target)
        # Use hostname for further queries if we got one
        domain = results["reverse_dns"] or target

    else:
        domain = target

        # Standard record lookups
        for rtype in ["A", "AAAA", "MX", "NS", "TXT", "SOA"]:
            results["records"][rtype] = _query(resolver, domain, rtype)

        # Zone transfer attempt against each NS
        ns_list = results["records"].get("NS", [])
        results["zone_transfer"] = _zone_transfer(domain, ns_list)

        # Subdomain brute-force
        results["subdomains"] = _brute_subdomains(resolver, domain)

    return results


def _reverse_lookup(ip: str) -> str:
    try:
        rev = dns.reversename.from_address(ip)
        answer = dns.resolver.resolve(rev, "PTR", lifetime=5)
        return str(answer[0]).rstrip(".")
    except Exception:
        try:
            return socket.gethostbyaddr(ip)[0]
        except Exception:
            return ""


def _query(resolver, domain: str, rtype: str) -> list:
    try:
        answers = resolver.resolve(domain, rtype)
        return [str(r).rstrip(".") for r in answers]
    except Exception:
        return []


def _zone_transfer(domain: str, ns_list: list) -> list:
    """Attempt AXFR zone transfer against each nameserver."""
    records = []
    for ns in ns_list[:3]:
        ns_host = ns.rstrip(".")
        try:
            zone = dns.zone.from_xfr(dns.query.xfr(ns_host, domain, timeout=5))
            for name in zone.nodes:
                records.append(f"{name}.{domain}")
            if records:
                break
        except Exception:
            continue
    return records


def _brute_subdomains(resolver, domain: str) -> list:
    """Brute-force common subdomains."""
    found = []
    for sub in COMMON_SUBDOMAINS:
        fqdn = f"{sub}.{domain}"
        try:
            resolver.resolve(fqdn, "A", lifetime=3)
            found.append(fqdn)
        except Exception:
            continue
    return found
