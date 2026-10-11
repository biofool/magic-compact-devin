# Security — magic-compact-devin

2026-10 security audit: hook + mcp_server input-handling hardening.

## Standing rules
- Never commit secrets (`.env`, `*.key`, `credentials*.json` are gitignored).
- Never read or log secret values — key names and lengths only.
- Security fixes land reviewed-but-uncommitted first, then roll dev → main.
