#!/usr/bin/env python3
"""Create or update the FarSight API Entra app registration and app role.

This script is intentionally standalone: it runs in an administrator shell and
uses Azure CLI + Microsoft Graph in the current tenant context.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid


GRAPH = "https://graph.microsoft.com/v1.0"
WRITABLE_APP_ROLE_KEYS = {"allowedMemberTypes", "description", "displayName", "id", "isEnabled", "value"}


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


def create_application(display_name: str) -> dict:
    body = {
        "displayName": display_name,
        "signInAudience": "AzureADMyOrg",
    }
    return graph("POST", "/applications", body)


def ensure_service_principal(app_id: str) -> dict:
    result = graph("GET", f"/servicePrincipals?$filter=appId eq '{app_id}'")
    values = result.get("value") or []
    if values:
        return values[0]
    return graph("POST", "/servicePrincipals", {"appId": app_id})


def normalize_role(role: dict) -> dict:
    return {key: role[key] for key in WRITABLE_APP_ROLE_KEYS if key in role}


def ensure_api_role(app: dict, role_value: str, role_display_name: str, role_description: str) -> tuple[list[dict], str]:
    app_roles = [normalize_role(role) for role in app.get("appRoles", [])]
    for role in app_roles:
        if role.get("value") != role_value:
            continue
        allowed_member_types = set(role.get("allowedMemberTypes", []))
        allowed_member_types.add("Application")
        role["allowedMemberTypes"] = sorted(allowed_member_types)
        role["displayName"] = role_display_name
        role["description"] = role_description
        role["isEnabled"] = True
        return app_roles, str(role["id"])

    role_id = str(uuid.uuid4())
    app_roles.append(
        {
            "id": role_id,
            "value": role_value,
            "displayName": role_display_name,
            "description": role_description,
            "allowedMemberTypes": ["Application"],
            "isEnabled": True,
        }
    )
    return app_roles, role_id


def ensure_identifier_uri(app: dict, requested_identifier_uri: str | None) -> tuple[list[str], str]:
    default_identifier_uri = f"api://{app['appId']}"
    identifier_uri = requested_identifier_uri or default_identifier_uri
    existing = list(app.get("identifierUris", []))
    if identifier_uri not in existing:
        existing.append(identifier_uri)
    return existing, identifier_uri


def update_application(app_object_id: str, identifier_uris: list[str], app_roles: list[dict]) -> None:
    graph(
        "PATCH",
        f"/applications/{app_object_id}",
        {
            "identifierUris": identifier_uris,
            "appRoles": app_roles,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision FarSight API Entra app registration and application role.")
    parser.add_argument("--display-name", default="Agent-Azure-FarSight API")
    parser.add_argument("--tenant-id", default=None, help="Tenant ID. Defaults to az account tenant.")
    parser.add_argument(
        "--identifier-uri",
        default=None,
        help="API application ID URI/audience (default: api://<client-id>).",
    )
    parser.add_argument("--role-value", default="Farsight.Api.Access")
    parser.add_argument("--role-display-name", default="Access FarSight API")
    parser.add_argument(
        "--role-description",
        default="Allows service principals to call protected FarSight API machine-to-machine endpoints.",
    )
    parser.add_argument("--output", choices=["json", "env"], default="env")
    args = parser.parse_args()

    tenant_id = args.tenant_id or az("account", "show", "--query", "tenantId", "-o", "tsv")
    app = find_application(args.display_name)
    created = False
    if app is None:
        app = create_application(args.display_name)
        created = True

    identifier_uris, selected_identifier_uri = ensure_identifier_uri(app, args.identifier_uri)
    app_roles, role_id = ensure_api_role(app, args.role_value, args.role_display_name, args.role_description)
    update_application(app["id"], identifier_uris, app_roles)

    app = graph("GET", f"/applications/{app['id']}")
    service_principal = ensure_service_principal(app["appId"])

    values = {
        "created": created,
        "tenantId": tenant_id,
        "applicationObjectId": app["id"],
        "servicePrincipalObjectId": service_principal["id"],
        "appRoleId": role_id,
        "FARSIGHT_API_APP_ID": app["appId"],
        "FARSIGHT_API_IDENTIFIER_URI": selected_identifier_uri,
        "FARSIGHT_API_REQUIRED_APP_ROLE": args.role_value,
        "FARSIGHT_API_ALLOWED_AUDIENCES": f"{selected_identifier_uri},{app['appId']}",
    }

    if args.output == "json":
        print(json.dumps(values, indent=2))
    else:
        for key in (
            "FARSIGHT_API_APP_ID",
            "FARSIGHT_API_IDENTIFIER_URI",
            "FARSIGHT_API_REQUIRED_APP_ROLE",
            "FARSIGHT_API_ALLOWED_AUDIENCES",
        ):
            print(f"{key}=\"{values[key]}\"")
        print("")
        print(f"# created={created}")
        print(f"# applicationObjectId={values['applicationObjectId']}")
        print(f"# servicePrincipalObjectId={values['servicePrincipalObjectId']}")
        print(f"# appRoleId={values['appRoleId']}")
        print("")
        print("# Next step: grant this app role to the SRE managed identity")
        print(
            f"# MI_CLIENT_ID=\"<sre-mi-client-id>\" FARSIGHT_API_APP_ID=\"{app['appId']}\" "
            f"FARSIGHT_API_ROLE_VALUE=\"{args.role_value}\" ./src/sre-agent/scripts/grant-farsight-api-access.sh"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
