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
- External kernels and every research input are hashed in manifests. Incremental
  provenance includes both the controls CSV and its strict controls catalog.

## Supported versions

Security fixes target `main` and the latest published GitHub Release. The
`2.2.0` source version is not a published release until its tag workflow
succeeds; older releases should upgrade before reporting a version-specific
issue.

Only download versioned artifacts after they appear on this repository's GitHub
Releases page. Verify the accompanying SHA-256 checksum before installation and,
when provenance is published, check it with
`gh attestation verify <artifact> --repo harryhuang0719/Destiny`.
