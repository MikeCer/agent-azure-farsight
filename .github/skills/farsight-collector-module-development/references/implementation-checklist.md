# Implementation checklist

Use this checklist when creating or changing a FarSight collector module.

## 1. Define the diagnostic scope

- What exact troubleshooting question does the module answer?
- What Intune data would lead an SRE agent to request this deeper endpoint evidence?
- What data must not be collected?
- Is the module read-only?
- Can the output be summarized without an artifact?

Reject designs that look like:

- remote shell;
- arbitrary file collector;
- arbitrary registry reader;
- arbitrary URL tester;
- generic script runner;
- unrestricted event-log dump.

## 2. Choose safe inputs

Prefer:

- `appId`
- `profile`
- `includeArtifact`
- `maxItems`
- `maxBytes`
- `startTimeUtc` / `endTimeUtc`
- explicit enums

For path-like modules:

- accept an app/profile ID;
- map the profile to approved roots inside module code or signed config;
- canonicalize requested paths with `Resolve-Path -LiteralPath`;
- reject paths outside approved roots after resolution;
- reject UNC paths, drive roots, traversal, and unsafe reparse points unless specifically designed and reviewed.

## 3. Implement PowerShell safely

- Use Windows PowerShell 5.1-compatible syntax.
- Use `Set-StrictMode -Version 2.0`.
- Use `$ErrorActionPreference = 'Stop'`.
- Use `try` / `catch` around the main operation and return a FarSight failure envelope.
- Use `-LiteralPath`.
- Avoid global environment mutations.
- Avoid service/process changes.
- Avoid network calls unless the module is explicitly a network diagnostic.
- Dispose cryptographic objects when created manually.

## 4. Handle artifacts

Artifacts should be:

- optional when possible;
- bounded by count, byte size, and time window;
- staged under `$OutputRoot/<ModuleName>/`;
- hashed with SHA-256;
- described by artifact metadata with `localPath`;
- redacted before packaging if text-based.

The collector owns upload:

```text
module writes local artifact -> collector prepare -> direct Blob PUT or API fallback -> commit -> result submit
```

Do not implement upload logic inside module scripts.

## 5. Add tests

At minimum, add Pester coverage for:

- required input validation;
- denied/unapproved profiles;
- no arbitrary paths;
- no traversal;
- bounded counts and byte caps;
- redaction behavior;
- artifact metadata includes `localPath`;
- graceful failure envelope;
- no-match or empty-result scenarios.

## 6. Update package and docs surfaces

- `src/modules/<ModuleName>/README.md`
- `docs/modules/README.md`
- `docs/extension-guide/` if the workflow changes
- `docs/security/README.md` if sensitivity or identity boundaries change
- `src/collector/config/module-manifest.sample.json` only when the default package should include the module
- `scripts/build-collector-intunewin.py` only if packaging behavior changes

## 7. Validate before final response

Run targeted checks:

```bash
pwsh -NoProfile -Command "[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'src/modules/<Module>/<Module>.ps1'), [ref]\$null) | Out-Null"
```

If Python/API/gateway/tooling changed:

```bash
python3 -m compileall <changed-python-files>
```

If frontend changed:

```bash
npm --prefix src/admin-web/frontend run build
```

If Bicep changed:

```bash
az bicep build -f infra/bicep/main.bicep --stdout > /dev/null
```

Only run tools that already exist in the repo or environment.

