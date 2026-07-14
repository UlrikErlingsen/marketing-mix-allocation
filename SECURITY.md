# Security policy

## Supported version

Security fixes are applied to the latest version on the `main` branch. Older release branches are not currently maintained.

## Report a vulnerability privately

Do not open a public issue for a suspected vulnerability involving file handling, code execution, dependency compromise, formula injection, or disclosure of uploaded plans or panel data. Email [code.modular578@passmail.net](mailto:code.modular578@passmail.net) with the subject `[AllocSignal security]`. If GitHub private vulnerability reporting is enabled for the planned repository, you may instead use its [private security advisory form](https://github.com/UlrikErlingsen/marketing-mix-allocation/security/advisories/new).

Please include:

- the affected version or commit;
- clear reproduction steps using synthetic data;
- the expected impact; and
- a suggested mitigation, if available.

Reports are reviewed on a best-effort basis; this volunteer project does not promise a formal response-time SLA. Never attach real business data, credentials, or other secrets.

## Scope and deployment responsibility

AllocSignal reads tabular CSV, Excel, and JSON. It does not accept serialized Python models or intentionally execute spreadsheet macros. Safe loaders should limit file size, workbook expansion, row count, and total cells; spreadsheet exports should neutralize formula-like text. The Docker image runs as an unprivileged user. These controls reduce risk but do not make an internet deployment safe by themselves.

Anyone exposing the app over a network remains responsible for authentication, TLS, network isolation, dependency updates, logging, secrets, backups, upload limits, retention, and incident response. Read [PRIVACY.md](PRIVACY.md) before accepting uploads.
