#!/usr/bin/env python3
"""Create or update the Entra app registration used by Container Apps Easy Auth.

The script is intentionally standalone: an administrator can run it manually, or
AZD can invoke it as a hook once the admin web redirect URI/custom domain is
known. It uses Azure CLI for Microsoft Graph calls so it follows the
administrator's existing login and tenant context.
"""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
from datetime import datetime, timedelta, timezone


GRAPH = "https://graph.microsoft.com/v1.0"


def az(*args: str, json_body: dict | None = None) -> str:
    command = ["az", *args]
    if json_body is not None:
        command.extend(["--body", json.dumps(json_body)])
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"az {' '.join(args[:3])} failed:\n{result.stderr.strip()}")
    return result.stdout.strip()


def graph(method: str, path: str, body: dict | None = None) -> dict:
    args = ["rest", "--method", method, "--url", f"{GRAPH}{path}", "--headers", "Content-Type=application/json"]
    output = az(*args, json_body=body)
    return json.loads(output) if output else {}


def find_application(display_name: str) -> dict | None:
    escaped = display_name.replace("'", "''")
    result = graph("GET", f"/applications?$filter=displayName eq '{escaped}'")
    values = result.get("value") or []
    return values[0] if values else None


def create_application(display_name: str, redirect_uris: list[str]) -> dict:
    body = {
        "displayName": display_name,
        "signInAudience": "AzureADMyOrg",
        "web": {
            "redirectUris": redirect_uris,
            "implicitGrantSettings": {
                "enableIdTokenIssuance": True,
                "enableAccessTokenIssuance": False,
            },
        },
    }
    return graph("POST", "/applications", body)


def update_application(app_object_id: str, redirect_uris: list[str]) -> None:
    graph("PATCH", f"/applications/{app_object_id}", {"web": {"redirectUris": redirect_uris}})


def ensure_service_principal(app_id: str) -> dict:
    result = graph("GET", f"/servicePrincipals?$filter=appId eq '{app_id}'")
    values = result.get("value") or []
    if values:
        return values[0]
    return graph("POST", "/servicePrincipals", {"appId": app_id})


def create_secret(app_object_id: str, display_name: str, months: int) -> str:
    end = datetime.now(timezone.utc) + timedelta(days=months * 31)
    body = {
        "passwordCredential": {
            "displayName": display_name,
            "endDateTime": end.isoformat().replace("+00:00", "Z"),
        }
    }
    result = graph("POST", f"/applications/{app_object_id}/addPassword", body)
    secret = result.get("secretText")
    if not secret:
        raise RuntimeError("Graph did not return secretText for the new client secret.")
    return secret


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision FarSight admin Entra app registration for Container Apps Easy Auth.")
    parser.add_argument("--display-name", default="Agent-Azure-FarSight Admin")
    parser.add_argument("--redirect-uri", action="append", required=True, help="Easy Auth callback URI, for example https://<host>/.auth/login/aad/callback")
    parser.add_argument("--tenant-id", default=None, help="Tenant ID. Defaults to az account tenant.")
    parser.add_argument("--create-secret", action="store_true", help="Create a client secret and include it in output.")
    parser.add_argument("--secret-months", type=int, default=6)
    parser.add_argument("--output", choices=["json", "env"], default="env")
    args = parser.parse_args()

    tenant_id = args.tenant_id or az("account", "show", "--query", "tenantId", "-o", "tsv")
    app = find_application(args.display_name)
    created = False
    if app is None:
        app = create_application(args.display_name, args.redirect_uri)
        created = True
    else:
        update_application(app["id"], args.redirect_uri)

    service_principal = ensure_service_principal(app["appId"])
    secret = create_secret(app["id"], "container-apps-easy-auth", args.secret_months) if args.create_secret else None
    values = {
        "created": created,
        "applicationObjectId": app["id"],
        "servicePrincipalObjectId": service_principal["id"],
        "FARSIGHT_ADMIN_AUTH_CLIENT_ID": app["appId"],
        "FARSIGHT_ADMIN_AUTH_ISSUER": f"https://login.microsoftonline.com/{tenant_id}/v2.0",
        "FARSIGHT_ADMIN_AUTH_ALLOWED_AUDIENCE": app["appId"],
    }
    if secret:
        values["FARSIGHT_ADMIN_AUTH_CLIENT_SECRET"] = secret

    if args.output == "json":
        print(json.dumps(values, indent=2))
    else:
        for key, value in values.items():
            if key.startswith("FARSIGHT_"):
                print(f"{key}=\"{value}\"")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
