# Get-AppDiskEvidence tests

Add Pester tests before promoting this sample to production code.

## Required cases

- Valid input accepts only `contoso-app` and `winget-cache`.
- Invalid input rejects arbitrary paths, extra properties, command text, excessive sample counts, and non-boolean flags.
- Module never writes files, changes services, changes registry keys, starts processes, or invokes arbitrary PowerShell.
- Returned paths redact usernames and user profiles.
- Timeout is enforced by the collector and produces a failure envelope.
- Missing allowlisted folders produce `path_missing` findings, not crashes.
- Failures return `status: failed` without sensitive exception details.

## Placeholder command

```powershell
Invoke-Pester -Path .\tests
```
