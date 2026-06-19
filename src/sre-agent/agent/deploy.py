#!/usr/bin/env python3
"""
Deploy Agent-Azure-FarSight SRE Agent content.

Uploads knowledge files, deploys Python tools from tools/*.yaml, deploys Skill
Builder skills from skills/*/skill.yaml, and deploys the Agent-Azure-FarSight
SRE custom agent through the Azure SRE Agent data-plane API.

Usage:
  python3 deploy.py --agent-name <sre-agent-resource-name>
  python3 deploy.py --agent-name <sre-agent-resource-name> --dry-run

When run by azd postdeploy, SRE_AGENT_NAME and AZURE_RESOURCE_GROUP are read
from Bicep outputs.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required. Install with: python3 -m pip install -r requirements.txt")
    sys.exit(1)

SCRIPT_DIR = Path(__file__).parent.resolve()

KB_FILES = [
    SCRIPT_DIR / "knowledge" / "agent.md",
    SCRIPT_DIR / "knowledge" / "intune-data-catalog.md",
    SCRIPT_DIR / "skills" / "intune-data-analysis" / "SKILL.md",
]
for farsight_skill in (
    "farsight-system-context",
    "farsight-tool-orchestration",
):
    skill_md = SCRIPT_DIR / "skills" / farsight_skill / "SKILL.md"
    if skill_md.exists():
        KB_FILES.append(skill_md)

AGENT_YAMLS = [
    SCRIPT_DIR / "agent-azure-farsight-sre.yaml",
]

SKILL_YAMLS = sorted((SCRIPT_DIR / "skills").glob("*/skill.yaml"))
TOOL_YAMLS = sorted((SCRIPT_DIR / "tools").glob("*.yaml"))
DEFAULT_TENANT_ID_SECRET_NAME = "intune-tenant-id"
DEFAULT_CLIENT_ID_SECRET_NAME = "intune-client-id"
DEFAULT_CLIENT_SECRET_SECRET_NAME = "intune-client-secret"
KEY_VAULT_SECRETS_USER_ROLE = "Key Vault Secrets User"
INTUNE_AUTH_MODE_ENV = "INTUNE_DIAGNOSTICS_AUTH_MODE"
INTUNE_AUTH_MODE_KEY_VAULT = "key-vault"
INTUNE_AUTH_MODE_MANAGED_IDENTITY = "managed-identity"
SRE_TOOL_ENDPOINT_URL_ENV = "SRE_AGENT_TOOL_ENDPOINT_URL"
SRE_TOOL_ENDPOINT_SCOPE_ENV = "SRE_AGENT_TOOL_ENDPOINT_SCOPE"
SRE_TOOL_AUTH_MODE_ENV = "SRE_AGENT_TOOL_AUTH_MODE"
DEPLOY_LOG_DIR = SCRIPT_DIR / ".logs"
_ACTIVE_LOG_HANDLE: Any = None


class TeeStream:
    def __init__(self, primary: Any, secondary: Any):
        self._primary = primary
        self._secondary = secondary

    def write(self, data: str) -> int:
        written = self._primary.write(data)
        self._secondary.write(data)
        return written

    def flush(self) -> None:
        self._primary.flush()
        self._secondary.flush()

    def isatty(self) -> bool:
        return bool(getattr(self._primary, "isatty", lambda: False)())

    def fileno(self) -> int:
        return self._primary.fileno()


def enable_persistent_console_log() -> Path:
    global _ACTIVE_LOG_HANDLE

    DEPLOY_LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    log_path = DEPLOY_LOG_DIR / f"deploy-{timestamp}.log"
    log_handle = log_path.open("w", encoding="utf-8", buffering=1)
    _ACTIVE_LOG_HANDLE = log_handle
    sys.stdout = TeeStream(sys.stdout, log_handle)
    sys.stderr = TeeStream(sys.stderr, log_handle)
    return log_path


class AzureCliError(RuntimeError):
    pass


def az(*args: str) -> str:
    executable = shutil.which("az") or shutil.which("az.cmd")
    if not executable:
        raise AzureCliError(
            "Azure CLI executable 'az' was not found in PATH. Install Azure CLI or run this script "
            "from the same shell/environment where `az account show` works."
        )
    try:
        result = subprocess.run([executable, *args], capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise AzureCliError(
            "Azure CLI executable 'az' was not found in PATH. Install Azure CLI or run this script "
            "from the same shell/environment where `az account show` works."
        ) from exc
    if result.returncode != 0:
        raise AzureCliError(f"az {' '.join(args[:3])} ... failed:\n{result.stderr.strip()}")
    return result.stdout.strip()


def load_azd_env_values() -> list[str]:
    """Load missing values from `azd env get-values` for direct script runs."""
    executable = shutil.which("azd") or shutil.which("azd.cmd")
    if not executable:
        return []
    try:
        result = subprocess.run(
            [executable, "env", "get-values"],
            cwd=SCRIPT_DIR,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return []
    if result.returncode != 0:
        return []

    loaded: list[str] = []
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        try:
            value = shlex.split(raw_value, posix=True)[0] if raw_value.strip() else ""
        except ValueError:
            value = raw_value.strip().strip('"')
        os.environ[key] = value
        loaded.append(key)
    return loaded


def normalize_tool_endpoint_scope() -> None:
    value = os.environ.get(SRE_TOOL_ENDPOINT_SCOPE_ENV, "").strip()
    if value.startswith("api://") and not value.endswith("/.default"):
        os.environ[SRE_TOOL_ENDPOINT_SCOPE_ENV] = f"{value.rstrip('/')}/.default"


def ensure_subscription_access(subscription: str | None) -> None:
    if not subscription:
        return

    try:
        az("account", "show", "--subscription", subscription, "--query", "id", "-o", "tsv")
    except AzureCliError as exc:
        raise RuntimeError(
            "Azure CLI cannot access the subscription configured for this azd environment.\n"
            f"Subscription: {subscription}\n\n"
            "The postdeploy hook uses the Azure CLI (`az`) from the hook shell. "
            "`azd` authentication and `az` authentication can be different, especially "
            "when `azure.yaml` uses `shell: sh` on Windows and the hook runs through WSL or Git Bash.\n\n"
            "Run these commands in the same shell/environment that executes the postdeploy hook:\n"
            f"  az login --tenant <tenant-id>\n"
            f"  az account set --subscription {subscription}\n"
            f"  az account show --query id -o tsv\n\n"
            "Then rerun `azd up` or rerun this script with the same --agent-name, "
            "--resource-group, and --subscription values."
        ) from exc


def get_token() -> str:
    token_resource = os.environ.get(
        "SRE_AGENT_TOKEN_RESOURCE",
        "59f0a04a-b322-4310-adc9-39ac41e9631e",
    )
    return az(
        "account",
        "get-access-token",
        "--resource",
        token_resource,
        "--query",
        "accessToken",
        "-o",
        "tsv",
    )


def resolve_endpoint(resource_group: str, agent_name: str, subscription: str | None) -> str:
    args = [
        "resource",
        "show",
        "--resource-type",
        "Microsoft.App/agents",
        "--name",
        agent_name,
        "--resource-group",
        resource_group,
        "--query",
        "properties",
        "-o",
        "json",
    ]
    if subscription:
        args += ["--subscription", subscription]

    props = json.loads(az(*args))
    power_state = str(props.get("powerState") or "").strip()
    running_state = str(props.get("runningState") or "").strip()
    if power_state and power_state.lower() == "stopped":
        raise RuntimeError(
            f"SRE Agent '{agent_name}' is stopped (powerState={power_state}, runningState={running_state or 'unknown'}). "
            "Start the SRE Agent before running deploy.py; stopped agents return HTTP 404 on data-plane routes."
        )
    endpoint = props.get("endpoint") or props.get("agentEndpoint")
    if not endpoint or endpoint in ("None", "null"):
        raise RuntimeError(
            f"Could not resolve endpoint for SRE Agent '{agent_name}' in resource group '{resource_group}'."
        )
    return endpoint.rstrip("/")


def resolve_agent_system_principal_id(resource_group: str, agent_name: str, subscription: str | None) -> str | None:
    args = [
        "resource",
        "show",
        "--resource-type",
        "Microsoft.App/agents",
        "--name",
        agent_name,
        "--resource-group",
        resource_group,
        "--query",
        "identity.principalId",
        "-o",
        "tsv",
    ]
    if subscription:
        args += ["--subscription", subscription]

    value = az(*args).strip()
    if not value or value in ("None", "null"):
        return None
    return value


def resolve_key_vault_uri(resource_group: str, subscription: str | None) -> str | None:
    args = [
        "keyvault",
        "list",
        "--resource-group",
        resource_group,
        "--query",
        "[?starts_with(name, 'kv-sre-farsight-')].properties.vaultUri | [0]",
        "-o",
        "tsv",
    ]
    if subscription:
        args += ["--subscription", subscription]

    value = az(*args).strip()
    if not value or value in ("None", "null"):
        return None
    return value


def key_vault_name_from_uri(key_vault_uri: str) -> str:
    host = urllib.parse.urlparse(key_vault_uri).netloc
    if not host:
        raise ValueError(f"Invalid Key Vault URI: {key_vault_uri}")
    return host.split(".")[0]


def resolve_key_vault_id(key_vault_uri: str, subscription: str | None) -> str:
    args = [
        "keyvault",
        "show",
        "--name",
        key_vault_name_from_uri(key_vault_uri),
        "--query",
        "id",
        "-o",
        "tsv",
    ]
    if subscription:
        args += ["--subscription", subscription]
    return az(*args).strip()


def ensure_key_vault_secret_access(
    key_vault_uri: str,
    principal_id: str | None,
    subscription: str | None,
    principal_label: str,
) -> None:
    if not principal_id:
        print(f"  {principal_label}: no principal ID found; Key Vault role assignment skipped")
        return

    key_vault_id = resolve_key_vault_id(key_vault_uri, subscription)
    list_args = [
        "role",
        "assignment",
        "list",
        "--assignee",
        principal_id,
        "--scope",
        key_vault_id,
        "--role",
        KEY_VAULT_SECRETS_USER_ROLE,
        "-o",
        "json",
    ]
    if subscription:
        list_args += ["--subscription", subscription]

    existing_assignments = json.loads(az(*list_args) or "[]")
    if existing_assignments:
        print(f"  {principal_label}: {KEY_VAULT_SECRETS_USER_ROLE} already assigned")
        return

    create_args = [
        "role",
        "assignment",
        "create",
        "--assignee-object-id",
        principal_id,
        "--assignee-principal-type",
        "ServicePrincipal",
        "--role",
        KEY_VAULT_SECRETS_USER_ROLE,
        "--scope",
        key_vault_id,
        "-o",
        "none",
    ]
    if subscription:
        create_args += ["--subscription", subscription]

    az(*create_args)
    print(f"  {principal_label}: assigned {KEY_VAULT_SECRETS_USER_ROLE}")


def http_call(
    method: str,
    url: str,
    token: str,
    body: bytes | None = None,
    content_type: str = "application/json",
) -> tuple[int, bytes]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": content_type,
    }
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def content_type_for(path: Path) -> str:
    match path.suffix.lower():
        case ".md":
            return "text/markdown"
        case ".txt":
            return "text/plain"
        case ".json":
            return "application/json"
        case ".yaml" | ".yml":
            return "application/yaml"
        case _:
            return "application/octet-stream"


def build_multipart(text_fields: dict[str, str], files: list[tuple[str, str, str, bytes]]) -> tuple[bytes, str]:
    boundary = f"----FormBoundary{uuid.uuid4().hex}"
    crlf = b"\r\n"
    parts: list[bytes] = []

    for name, value in text_fields.items():
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n'
                f"\r\n{value}\r\n"
            ).encode()
        )

    for field_name, filename, mime_type, content in files:
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
                f"Content-Type: {mime_type}\r\n"
                f"\r\n"
            ).encode()
            + content
            + crlf
        )

    return b"".join(parts) + f"--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


def yaml_to_agent_api_body(yaml_path: Path) -> dict[str, Any]:
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    spec = data.get("spec", data)
    enable_skills = spec.get("enable_skills")
    if enable_skills is None:
        enable_skills = True

    return {
        "name": spec["name"],
        "type": "ExtendedAgent",
        "tags": [],
        "owner": "",
        "properties": {
            "instructions": inject_runtime_defaults(spec.get("system_prompt", "")),
            "handoffDescription": spec.get("handoff_description", ""),
            "handoffs": spec.get("handoff_agents", spec.get("handoffs", [])),
            "tools": spec.get("tools", []),
            "mcpTools": spec.get("mcp_tools", []),
            "allowParallelToolCalls": True,
            "enableSkills": enable_skills,
            "allowedSkills": spec.get("allowed_skills", []),
        },
    }


def skill_yaml_to_api_body(skill_yaml_path: Path) -> dict[str, Any]:
    meta = yaml.safe_load(skill_yaml_path.read_text(encoding="utf-8"))
    skill_dir = skill_yaml_path.parent
    skill_name = meta["name"]
    files = meta.get("files") or ["SKILL.md"]
    skill_md_path = skill_dir / "SKILL.md"
    if not skill_md_path.exists():
        raise FileNotFoundError(f"Missing SKILL.md for skill '{skill_name}': {skill_md_path}")

    additional_files = []
    for rel_file in files:
        file_path = skill_dir / rel_file
        if not file_path.exists():
            raise FileNotFoundError(f"Missing listed skill file for '{skill_name}': {file_path}")
        if rel_file == "SKILL.md":
            continue
        additional_files.append(
            {
                "filePath": rel_file,
                "content": file_path.read_text(encoding="utf-8"),
            }
        )

    return {
        "name": skill_name,
        "type": "Skill",
        "properties": {
            "description": (meta.get("description") or "").strip(),
            "tools": meta.get("tools") or [],
            "skillContent": inject_runtime_defaults(skill_md_path.read_text(encoding="utf-8")),
            "additionalFiles": additional_files,
        },
    }


def inject_runtime_defaults(content: str) -> str:
    # --- SRE tool endpoint URL ---
    farsight_api_base_url = os.environ.get(SRE_TOOL_ENDPOINT_URL_ENV, "").strip().rstrip("/")
    content = content.replace("{{FARSIGHT_API_BASE_URL}}", farsight_api_base_url)

    # --- SRE tool endpoint scope ---
    farsight_api_scope = os.environ.get(SRE_TOOL_ENDPOINT_SCOPE_ENV, "").strip()
    content = content.replace("{{FARSIGHT_API_SCOPE}}", farsight_api_scope)

    # --- Intune auth mode ---
    auth_mode = os.environ.get(INTUNE_AUTH_MODE_ENV, INTUNE_AUTH_MODE_MANAGED_IDENTITY).strip().lower()
    if auth_mode == INTUNE_AUTH_MODE_MANAGED_IDENTITY:
        return (
            content.replace(
                "{{INTUNE_KEY_VAULT_TOOL_ARGUMENTS}}",
                '"auth_mode": "default"',
            )
            .replace(
                "{{INTUNE_AUTH_MODE_GUIDANCE}}",
                "Use this managed-identity call shape unless the user explicitly asks to use Key Vault or direct service-principal credentials. The SRE Agent assigned identity must have the required Microsoft Graph/Intune application permissions.",
            )
        )
    if auth_mode != INTUNE_AUTH_MODE_KEY_VAULT:
        raise ValueError(
            f"Unsupported {INTUNE_AUTH_MODE_ENV} value '{auth_mode}'. "
            f"Use '{INTUNE_AUTH_MODE_KEY_VAULT}' or '{INTUNE_AUTH_MODE_MANAGED_IDENTITY}'."
        )

    key_vault_uri = os.environ.get("INTUNE_DIAGNOSTICS_KEY_VAULT_URI", "").strip()
    if not key_vault_uri:
        return (
            content.replace(
                "{{INTUNE_KEY_VAULT_TOOL_ARGUMENTS}}",
                '"auth_mode": "client-secret"',
            )
            .replace(
                "{{INTUNE_AUTH_MODE_GUIDANCE}}",
                "Use Key Vault credentials when collecting evidence. If Key Vault parameters are omitted, the tool may fall back to the SRE Agent tenant identity instead of the Intune tenant credentials.",
            )
        )

    return (
        content.replace(
            "{{INTUNE_KEY_VAULT_TOOL_ARGUMENTS}}",
            (
                '"auth_mode": "client-secret",\n'
                f'  "key_vault_url": "{key_vault_uri}",\n'
                f'  "tenant_id_secret_name": "{DEFAULT_TENANT_ID_SECRET_NAME}",\n'
                f'  "client_id_secret_name": "{DEFAULT_CLIENT_ID_SECRET_NAME}",\n'
                f'  "client_secret_secret_name": "{DEFAULT_CLIENT_SECRET_SECRET_NAME}"'
            ),
        )
        .replace(
            "{{INTUNE_AUTH_MODE_GUIDANCE}}",
            "Use Key Vault credentials when collecting evidence. If Key Vault parameters are omitted, the tool may fall back to the SRE Agent tenant identity instead of the Intune tenant credentials.",
        )
    )


def intune_tool_parameter_defaults() -> dict[str, Any]:
    auth_mode = os.environ.get(INTUNE_AUTH_MODE_ENV, INTUNE_AUTH_MODE_MANAGED_IDENTITY).strip().lower()
    if auth_mode == INTUNE_AUTH_MODE_MANAGED_IDENTITY:
        return {"auth_mode": "default"}
    if auth_mode != INTUNE_AUTH_MODE_KEY_VAULT:
        raise ValueError(
            f"Unsupported {INTUNE_AUTH_MODE_ENV} value '{auth_mode}'. "
            f"Use '{INTUNE_AUTH_MODE_KEY_VAULT}' or '{INTUNE_AUTH_MODE_MANAGED_IDENTITY}'."
        )

    defaults: dict[str, Any] = {"auth_mode": "client-secret"}
    key_vault_uri = os.environ.get("INTUNE_DIAGNOSTICS_KEY_VAULT_URI", "").strip()
    if key_vault_uri:
        defaults.update(
            {
                "key_vault_url": key_vault_uri,
                "tenant_id_secret_name": DEFAULT_TENANT_ID_SECRET_NAME,
                "client_id_secret_name": DEFAULT_CLIENT_ID_SECRET_NAME,
                "client_secret_secret_name": DEFAULT_CLIENT_SECRET_SECRET_NAME,
            }
        )
    return defaults


def farsight_tool_defaults() -> dict[str, Any]:
    """Returns deployment-time defaults for SRE gateway tools."""
    defaults: dict[str, Any] = {}
    api_base_url = os.environ.get(SRE_TOOL_ENDPOINT_URL_ENV, "").strip().rstrip("/")
    if api_base_url:
        defaults["api_base_url"] = api_base_url
    api_scope = os.environ.get(SRE_TOOL_ENDPOINT_SCOPE_ENV, "").strip()
    if api_scope:
        defaults["api_scope"] = api_scope
    auth_mode = os.environ.get(SRE_TOOL_AUTH_MODE_ENV, "").strip().lower().replace("_", "-")
    defaults["farsight_auth_mode"] = auth_mode or "default"
    return defaults


def apply_parameter_defaults(parameters: list[dict[str, Any]], defaults: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for parameter in parameters:
        item = dict(parameter)
        name = item.get("name")
        if name in defaults:
            item["default"] = defaults[name]
            item["description"] = f"{item.get('description', '').rstrip()} Defaults to {defaults[name]!r} for this deployment."
        result.append(item)
    return result


def inject_tool_code_defaults(function_code: str, defaults: dict[str, Any]) -> str:
    replacements = {
        "__INTUNE_DEFAULT_AUTH_MODE__": str(defaults.get("auth_mode") or ""),
        "__INTUNE_DEFAULT_KEY_VAULT_URL__": str(defaults.get("key_vault_url") or ""),
        "__INTUNE_DEFAULT_TENANT_ID_SECRET_NAME__": str(defaults.get("tenant_id_secret_name") or ""),
        "__INTUNE_DEFAULT_CLIENT_ID_SECRET_NAME__": str(defaults.get("client_id_secret_name") or ""),
        "__INTUNE_DEFAULT_CLIENT_SECRET_SECRET_NAME__": str(defaults.get("client_secret_secret_name") or ""),
        "__SRE_AGENT_TOOL_ENDPOINT_URL__": str(defaults.get("api_base_url") or ""),
        "__SRE_AGENT_TOOL_AUTH_MODE__": str(defaults.get("farsight_auth_mode") or ""),
        "__SRE_AGENT_TOOL_ENDPOINT_SCOPE__": str(defaults.get("api_scope") or ""),
    }
    for placeholder, value in replacements.items():
        function_code = function_code.replace(placeholder, value)
    return function_code


def tool_yaml_to_api_body(tool_yaml_path: Path) -> dict[str, Any]:
    spec = yaml.safe_load(tool_yaml_path.read_text(encoding="utf-8"))
    tool_dir = tool_yaml_path.parent
    code_file = spec.get("code_file")
    if not code_file:
        raise ValueError(f"Missing code_file in tool YAML: {tool_yaml_path}")

    code_path = tool_dir / code_file
    if not code_path.exists():
        raise FileNotFoundError(f"Missing code file for tool '{spec['name']}': {code_path}")
    function_code = code_path.read_text(encoding="utf-8-sig").lstrip("\ufeff")
    defaults = {**intune_tool_parameter_defaults(), **farsight_tool_defaults()}
    function_code = inject_tool_code_defaults(function_code, defaults)
    parameters = apply_parameter_defaults(spec.get("parameters") or [], defaults)

    return {
        "name": spec["name"],
        "type": "ExtendedAgentTool",
        "tags": spec.get("tags") or [],
        "properties": {
            "type": spec.get("type", "PythonFunctionTool"),
            "description": (spec.get("description") or "").strip(),
            "parameters": parameters,
            "functionCode": function_code,
            "dependencies": spec.get("dependencies") or [],
            "authEnabled": spec.get("auth_enabled", False),
            "authScopes": spec.get("auth_scopes"),
            "connector": spec.get("connector"),
            "attributes": spec.get("attributes") or [],
            "timeoutSeconds": spec.get("timeout_seconds", 120),
            "toolMode": spec.get("tool_mode", "Auto"),
        },
    }


def upload_kb(endpoint: str, token: str, dry_run: bool, require_kb: bool = False) -> None:
    print("\nUploading knowledge base files...")
    missing = [path for path in KB_FILES if not path.exists()]
    if missing:
        for path in missing:
            print(f"  missing: {path}")
        raise FileNotFoundError("One or more KB files are missing.")

    if dry_run:
        for path in KB_FILES:
            print(f"  [dry-run] would upload {path.relative_to(SCRIPT_DIR)}")
        return

    body, content_type = build_multipart(
        text_fields={},
        files=[("files", path.name, content_type_for(path), path.read_bytes()) for path in KB_FILES],
    )
    candidate_paths = [
        "/api/v1/agentmemory/upload?triggerIndexing=true",
        "/api/v2/agentmemory/upload?triggerIndexing=true",
        "/api/v2/extendedAgent/agentmemory/upload?triggerIndexing=true",
        "/api/v2/extendedAgent/knowledge/upload?triggerIndexing=true",
    ]
    response = b""
    selected_path = ""
    for path in candidate_paths:
        status, response = http_call("POST", f"{endpoint}{path}", token, body, content_type)
        if status in (200, 201, 202):
            selected_path = path
            break
        if status != 404:
            raise RuntimeError(f"KB upload failed: HTTP {status}\n{response[:500].decode(errors='replace')}")
    else:
        message = (
            "KB upload skipped: every known AgentMemory upload endpoint returned HTTP 404. "
            f"Tried: {', '.join(candidate_paths)}"
        )
        if require_kb:
            raise RuntimeError(f"{message}\n{response[:500].decode(errors='replace')}")
        print(f"  warning: {message}")
        print("  continuing with tool, skill, and agent deployment")
        return
    print(f"  uploaded {len(KB_FILES)} file(s), HTTP {status} via {selected_path}")
    try:
        result = json.loads(response or b"{}")
    except json.JSONDecodeError:
        result = {}
    uploaded = result.get("uploaded")
    if uploaded:
        print(f"  accepted by service: {', '.join(uploaded)}")


def verify_kb_indexing(endpoint: str, token: str) -> None:
    candidate_paths = [
        "/api/v1/agentmemory/indexer-status",
        "/api/v2/agentmemory/indexer-status",
        "/api/v2/extendedAgent/agentmemory/indexer-status",
        "/api/v2/extendedAgent/knowledge/indexer-status",
    ]
    response = b""
    for path in candidate_paths:
        status, response = http_call("GET", f"{endpoint}{path}", token)
        if status == 200:
            break
        if status != 404:
            print(f"  could not check KB indexer status: HTTP {status}")
            return
    else:
        print("  could not check KB indexer status: no known AgentMemory status endpoint was found")
        return

    data = json.loads(response)
    last_execution = data.get("lastExecution") or {}
    print(
        "  KB indexer: "
        f"{data.get('status', 'unknown')}, "
        f"last execution {last_execution.get('status', 'unknown')}, "
        f"processed {last_execution.get('documentsProcessed', 0)}, "
        f"failed {last_execution.get('documentsFailed', 0)}"
    )
    errors = last_execution.get("itemErrors") or data.get("errors") or []
    if errors:
        print(f"  KB indexer errors: {json.dumps(errors)[:500]}")


def deploy_tools(endpoint: str, dry_run: bool) -> None:
    print("\nDeploying tools...")
    if not TOOL_YAMLS:
        print("  no tool YAML files found")
        return

    for tool_yaml in TOOL_YAMLS:
        body_dict = tool_yaml_to_api_body(tool_yaml)
        tool_name = body_dict["name"]
        if dry_run:
            props = body_dict["properties"]
            print(
                f"  [dry-run] {tool_name}: "
                f"{props.get('type')}, "
                f"{len(props.get('parameters') or [])} parameter(s)"
            )
            continue

        token = get_token()
        status, response = http_call(
            "PUT",
            f"{endpoint}/api/v2/extendedAgent/tools/{urllib.parse.quote(tool_name, safe='')}",
            token,
            json.dumps(body_dict).encode(),
        )
        if status in (200, 201, 202, 204):
            print(f"  {tool_name}: HTTP {status}")
        else:
            raise RuntimeError(f"Tool deployment failed for {tool_name}: HTTP {status}\n{response[:500].decode(errors='replace')}")


def deploy_skills(endpoint: str, dry_run: bool) -> None:
    print("\nDeploying skills...")
    if not SKILL_YAMLS:
        print("  no skill.yaml files found")
        return

    for skill_yaml in SKILL_YAMLS:
        body_dict = skill_yaml_to_api_body(skill_yaml)
        skill_name = body_dict["name"]
        if dry_run:
            print(f"  [dry-run] {skill_name}")
            continue

        token = get_token()
        status, response = http_call(
            "PUT",
            f"{endpoint}/api/v2/extendedAgent/skills/{skill_name}",
            token,
            json.dumps(body_dict).encode(),
        )
        if status in (200, 201, 202, 204):
            print(f"  {skill_name}: HTTP {status}")
        else:
            raise RuntimeError(f"Skill deployment failed for {skill_name}: HTTP {status}\n{response[:500].decode(errors='replace')}")


def deploy_agents(endpoint: str, dry_run: bool) -> None:
    print("\nDeploying custom agents...")
    for agent_yaml in AGENT_YAMLS:
        if not agent_yaml.exists():
            raise FileNotFoundError(f"Missing agent YAML: {agent_yaml}")
        body_dict = yaml_to_agent_api_body(agent_yaml)
        agent_name = body_dict["name"]
        if dry_run:
            props = body_dict["properties"]
            print(
                f"  [dry-run] {agent_name}: "
                f"{len(props.get('tools') or [])} tools, "
                f"{len(props.get('allowedSkills') or [])} skill(s)"
            )
            continue

        token = get_token()
        status, response = http_call(
            "PUT",
            f"{endpoint}/api/v2/extendedAgent/agents/{agent_name}",
            token,
            json.dumps(body_dict).encode(),
        )
        if status in (200, 201, 202, 204):
            print(f"  {agent_name}: HTTP {status}")
        else:
            raise RuntimeError(f"Agent deployment failed for {agent_name}: HTTP {status}\n{response[:500].decode(errors='replace')}")


def verify(endpoint: str, token: str) -> None:
    print("\nVerifying deployment...")

    verify_kb_indexing(endpoint, token)

    status, response = http_call("GET", f"{endpoint}/api/v2/extendedAgent/tools", token)
    if status == 200:
        data = json.loads(response)
        items = data.get("value", data) if isinstance(data, dict) else data
        live = {item.get("name") for item in (items or []) if isinstance(item, dict)}
        for tool_yaml in TOOL_YAMLS:
            expected = yaml.safe_load(tool_yaml.read_text(encoding="utf-8"))["name"]
            print(f"  tool {expected}: {'ok' if expected in live else 'not found'}")
    else:
        print(f"  could not list tools: HTTP {status}")

    status, response = http_call("GET", f"{endpoint}/api/v2/extendedAgent/skills", token)
    if status == 200:
        data = json.loads(response)
        items = data.get("value", data) if isinstance(data, dict) else data
        live = {item.get("name") for item in (items or []) if isinstance(item, dict)}
        for skill_yaml in SKILL_YAMLS:
            expected = yaml.safe_load(skill_yaml.read_text(encoding="utf-8"))["name"]
            print(f"  skill {expected}: {'ok' if expected in live else 'not found'}")
    else:
        print(f"  could not list skills: HTTP {status}")

    status, response = http_call("GET", f"{endpoint}/api/v2/extendedAgent/agents", token)
    if status == 200:
        data = json.loads(response)
        items = data.get("value", data) if isinstance(data, dict) else data
        live = {item.get("name") for item in (items or []) if isinstance(item, dict)}
        for agent_yaml in AGENT_YAMLS:
            expected = yaml.safe_load(agent_yaml.read_text(encoding="utf-8"))["spec"]["name"]
            print(f"  agent {expected}: {'ok' if expected in live else 'not found'}")
    else:
        print(f"  could not list agents: HTTP {status}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deploy Agent-Azure-FarSight SRE Agent content.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--agent-name", "-n", default=None, help="SRE Agent ARM resource name. Falls back to SRE_AGENT_NAME.")
    parser.add_argument("--resource-group", "-g", default=None, help="Resource group containing the SRE Agent. Falls back to AZURE_RESOURCE_GROUP.")
    parser.add_argument("--subscription", "-s", default=None, help="Azure subscription ID. Falls back to AZURE_SUBSCRIPTION_ID.")
    parser.add_argument("--skip-kb", action="store_true", help="Skip knowledge base upload.")
    parser.add_argument("--require-kb", action="store_true", help="Fail deployment if AgentMemory upload endpoints are unavailable.")
    parser.add_argument("--skip-tools", action="store_true", help="Skip Python tool deployment.")
    parser.add_argument("--skip-skills", action="store_true", help="Skip Skill Builder skill deployment.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned actions without API calls.")
    return parser.parse_args()


def default_resource_group() -> str:
    explicit = os.environ.get("AZURE_RESOURCE_GROUP")
    if explicit:
        return explicit
    environment_name = os.environ.get("AZURE_ENV_NAME")
    if environment_name:
        return f"rg-{environment_name}"
    return "rg-agent-azure-farsight-sre"


def main() -> None:
    log_path = enable_persistent_console_log()
    args = parse_args()
    loaded_azd_env_keys = load_azd_env_values()
    normalize_tool_endpoint_scope()
    agent_name = args.agent_name or os.environ.get("SRE_AGENT_NAME")
    resource_group = args.resource_group or default_resource_group()
    subscription = args.subscription or os.environ.get("AZURE_SUBSCRIPTION_ID")
    intune_auth_mode = os.environ.get(INTUNE_AUTH_MODE_ENV, INTUNE_AUTH_MODE_MANAGED_IDENTITY).strip().lower()

    if not agent_name:
        print("ERROR: provide --agent-name or set SRE_AGENT_NAME.")
        sys.exit(1)

    print("\n" + "=" * 62)
    print("  Agent-Azure-FarSight SRE Agent - Deploy")
    print("=" * 62)
    print(f"  Resource group : {resource_group}")
    print(f"  Agent name     : {agent_name}")
    if subscription:
        print(f"  Subscription   : {subscription}")
    print(f"  Skip KB        : {args.skip_kb}")
    print(f"  Skip Tools     : {args.skip_tools}")
    print(f"  Skip Skills    : {args.skip_skills}")
    print(f"  Dry run        : {args.dry_run}")
    print(f"  Log file       : {log_path}")
    if loaded_azd_env_keys:
        print(f"  AZD env loaded : {len(loaded_azd_env_keys)} value(s)")
    farsight_api_base_url = os.environ.get(SRE_TOOL_ENDPOINT_URL_ENV, "").strip()
    if farsight_api_base_url:
        print(f"  Tool Endpoint  : {farsight_api_base_url}")
    else:
        print(f"  Tool Endpoint  : (not set — tools will require api_base_url per call)")
    farsight_api_scope = os.environ.get(SRE_TOOL_ENDPOINT_SCOPE_ENV, "").strip()
    if farsight_api_scope:
        print(f"  Tool Scope     : {farsight_api_scope}")
    else:
        print(f"  Tool Scope     : (not set — tools will fall back to {{api_base_url}}/.default)")

    if args.dry_run:
        endpoint = "https://DRY-RUN-ENDPOINT"
        token = "DRY-RUN-TOKEN"
        print("\nDry run: endpoint resolution and API calls are skipped.")
    else:
        print("\nChecking Azure CLI subscription access...")
        ensure_subscription_access(subscription)
        print("  subscription accessible")
        print("\nResolving SRE Agent endpoint...")
        endpoint = resolve_endpoint(resource_group, agent_name, subscription)
        print(f"  {endpoint}")
        print("\nIntune diagnostics auth mode:")
        print(f"  {intune_auth_mode}")
        if intune_auth_mode == INTUNE_AUTH_MODE_KEY_VAULT:
            key_vault_uri = os.environ.get("INTUNE_DIAGNOSTICS_KEY_VAULT_URI") or resolve_key_vault_uri(resource_group, subscription)
            if key_vault_uri:
                os.environ["INTUNE_DIAGNOSTICS_KEY_VAULT_URI"] = key_vault_uri
                print("\nResolved Intune diagnostics Key Vault:")
                print(f"  {key_vault_uri}")
                print("\nEnsuring Key Vault secret read access...")
                system_principal_id = resolve_agent_system_principal_id(resource_group, agent_name, subscription)
                ensure_key_vault_secret_access(key_vault_uri, system_principal_id, subscription, "agent system-assigned identity")
            else:
                print("\nIntune diagnostics Key Vault not found; tool instructions will not include Key Vault defaults.")
        elif intune_auth_mode == INTUNE_AUTH_MODE_MANAGED_IDENTITY:
            os.environ.pop("INTUNE_DIAGNOSTICS_KEY_VAULT_URI", None)
            print("  using SRE Agent assigned identity for Microsoft Graph authentication")
        else:
            raise ValueError(
                f"Unsupported {INTUNE_AUTH_MODE_ENV} value '{intune_auth_mode}'. "
                f"Use '{INTUNE_AUTH_MODE_KEY_VAULT}' or '{INTUNE_AUTH_MODE_MANAGED_IDENTITY}'."
            )
        print("\nGetting bearer token...")
        token = get_token()
        print("  token obtained")

    if not args.skip_kb:
        upload_kb(endpoint, token, args.dry_run, require_kb=args.require_kb)
    else:
        print("\nKB upload skipped")

    if not args.skip_tools:
        deploy_tools(endpoint, args.dry_run)
    else:
        print("\nTool deployment skipped")

    if not args.skip_skills:
        deploy_skills(endpoint, args.dry_run)
    else:
        print("\nSkill deployment skipped")

    deploy_agents(endpoint, args.dry_run)

    if not args.dry_run:
        verify(endpoint, get_token())

    print("\n" + "=" * 62)
    print("  Done")
    print("=" * 62)
    print("\nNext steps:")
    print("  1. Open https://sre.azure.com -> Builder -> Agent Canvas.")
    print("  2. Confirm the Agent-Azure-FarSight SRE custom agent is visible.")
    print(
        "  3. Confirm the intune_diagnostics_tool tool and "
        "intune-data-analysis/farsight-system-context/"
        "farsight-tool-orchestration skills are attached."
    )
    print("  4. Run a prompt such as: Analyze recent Azure signals for operational risks and recommended actions.")
    if intune_auth_mode == INTUNE_AUTH_MODE_MANAGED_IDENTITY:
        print("\nManaged identity reminder:")
        print(
            "  Assign Microsoft Graph Intune application permissions with admin consent "
            "to the SRE Agent identity used at runtime (system-assigned or user-assigned)."
        )
        print("  Required permissions are documented in README (for example DeviceManagement*.Read.All and User.Read.All).")
    print(f"\nSaved deploy output to: {log_path}")


if __name__ == "__main__":
    main()
