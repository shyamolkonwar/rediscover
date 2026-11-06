# Security and scope

This is a local, single-user educational analysis tool. It is not a public multi-tenant service or an adversarial-code sandbox.

- The MCP server uses stdio only. No unauthenticated public HTTP service is started.
- No host shell, file deletion, arbitrary URL download or upload tool is exposed. Generated research Python is disabled by default; explicit operator opt-in enables the restricted Docker executor described in `docs/RESEARCH_SANDBOX.md`. This is not a perfect isolation boundary against kernel exploits.
- Data requests use an HTTPS hostname allowlist and validate each redirect, with bounded response sizes.
- Input samples are parsed as HDF5 and NumPy with `allow_pickle=False`. Keep native numerical libraries updated.
- Run IDs and artifact names are restricted; symlink escapes are rejected. A malicious local OS account with write access can still alter data and checksums. A checksum manifest is not a signature.
- MCP host approval controls apply. Tools create local cache/report files and can perform CPU work. Use a dedicated workspace and avoid exposing stdio through an unauthenticated bridge.
- Azure/API credentials are environment-only, never written into evidence bundles. The agent sends task metadata and numerical tool results to your configured provider. `store=false` is requested; provider retention terms still apply.
- Opaque benchmark truth is not accessible through the bounded agent tools. It is visible to the person running the benchmark and is not a secure evaluation against an adversarial operator.

Report security issues through GitHub private vulnerability reporting rather than posting exploit details in a public issue. If unavailable, open a minimal issue asking for a private reporting channel without disclosing sensitive details.
