# App disk evidence agent tool sample

This sample shows how an Azure SRE Agent tool can create a FarSight `Get-AppDiskEvidence` job without exposing arbitrary PowerShell.

## Files

- `create_app_disk_evidence_job.py` - typed tool sample with policy evaluation and `POST /api/v1/jobs` mapping.
- `tool-contract.json` - tool input schema.
- `../policies/agt-extension-policy.yaml` - sample AGT policy outcomes.

## Local dry run

```bash
python3 create_app_disk_evidence_job.py <<'JSON'
{
  "targetDeviceId": "device-001",
  "profile": "contoso-app",
  "includeFileSamples": true,
  "maxFileSamples": 5,
  "justification": "Investigate approved application disk growth."
}
JSON
```

Without `FARSIGHT_API_BASE_URL` and `FARSIGHT_ACCESS_TOKEN`, the sample prints a dry-run job request.

## Production wiring

- Replace token environment variables with managed identity token acquisition.
- Enforce the AGT policy bundle before API calls.
- Require approval for broad targets, sensitive devices, and larger sample requests.
- Preserve idempotency and audit fields.
- Return job metadata only; retrieve evidence through authorized FarSight APIs.
