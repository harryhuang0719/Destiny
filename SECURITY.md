# Security policy

## Reporting

Please report suspected vulnerabilities through a private GitHub security
advisory for `harryhuang0719/Destiny` when available. Do not include real birth
records, API keys, market-data credentials, or proprietary datasets in a public issue.

## Security model

- Core calculations are local and need no network.
- LLM calls occur only with explicit `--llm --provider ...`.
- The Node bridge receives validated JSON through stdin and an environment allowlist.
- User questions must travel through stdin or a temporary file, not shell interpolation.
- Historical modules never fetch market data and never fetch a JPL kernel implicitly.
- External kernels and every research input are hashed in manifests.

## Supported versions

Security fixes always target `main`. Once a `2.1.x` GitHub Release is actually
published, the latest release in that line is supported as well; older releases
should upgrade before reporting a version-specific issue.

Only download versioned artifacts after they appear on this repository's GitHub
Releases page. Verify the accompanying SHA-256 checksum before installation and,
when provenance is published, check it with
`gh attestation verify <artifact> --repo harryhuang0719/Destiny`.
