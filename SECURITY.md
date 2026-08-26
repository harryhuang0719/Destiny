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

Security fixes target the latest `main` branch until versioned releases are published.
