# AllocSignal privacy notes

AllocSignal is designed to run locally. It includes no user accounts, advertising, product analytics, telemetry, external AI calls, or built-in research-data database.

## When you run it on your computer

- Uploaded files are read into the Streamlit process on that computer.
- Analysis happens in memory; AllocSignal does not intentionally send channel plans or panel data to the project maintainer or a third-party API.
- Source files are never modified.
- Exports are created only when requested.
- Closing the process clears the in-memory session. The app itself does not persist an upload.

The launchers may contact Python package indexes on first use to install open-source dependencies. That installation traffic does not include uploaded analysis data.

## Data minimization

Allocation planning needs channel-level assumptions, not customer records. Panel analysis needs a stable entity key, time, outcome, and chosen predictors. Use pseudonymous unit labels and remove names, email addresses, phone numbers, postal addresses, account identifiers, free text, and unused columns before upload.

Even aggregate marketing plans can be commercially sensitive. Response ceilings, margins, spend commitments, regional results, prices, and distribution may reveal strategy. Apply your organization's access, retention, sharing, and deletion rules.

## Exports

Exports may contain channel budgets, curve assumptions, economics, model outputs, panel summaries, settings, warnings, and a source fingerprint. Treat every export as potentially confidential. Spreadsheet exports should be opened only in trusted software and shared through approved channels.

## When someone hosts it

A hosted deployment changes the trust boundary: uploaded files travel to and are processed by the selected server. The deployment operator—not this source tree—controls and is responsible for:

- authentication and authorization;
- TLS and network controls;
- infrastructure and application logs;
- backups, retention, deletion, and incident response;
- hosting jurisdiction; and
- privacy notices, consent, contracts, and applicable law.

The AllocSignal code does not add persistent upload storage, but a host or its infrastructure may. Do not upload confidential, personal, or regulated data until the operator has documented those controls.

## Reporting a privacy or security concern

Email [code.modular578@passmail.net](mailto:code.modular578@passmail.net) with the subject `[AllocSignal privacy]`. If private vulnerability reporting is enabled at the planned GitHub repository, its [private security advisory form](https://github.com/UlrikErlingsen/marketing-mix-allocation/security/advisories/new) is also suitable. Never put sensitive data or an exploitable report in a public issue.
