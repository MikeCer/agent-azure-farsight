#!/usr/bin/env python3
"""Safe Azure SRE Agent PythonFunctionTool for local ZIP workspace extraction."""
from __future__ import annotations

import os
import zipfile
from pathlib import Path
from typing import Any

_COMMAND_TOKENS = (";", "|", "`", "$(", "\n", "\r", "&&", "||")
_DEFAULT_OUTPUT_DIR_NAME = "farsight-extracted"


def _error(action: str, code: str, message: str, details: Any | None = None) -> dict:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"status": "error", "action": action, "error": error}


def _success(action: str, response: Any) -> dict:
    return {"status": "success", "action": action, "response": response}


def _has_command_tokens(value: str) -> bool:
    return any(token in value for token in _COMMAND_TOKENS)


def _validate_text(action: str, field: str, value: str | None, *, required: bool = False, max_len: int = 512) -> dict | None:
    if value is None or value == "":
        if required:
            return _error(action, "invalid_request", f"Missing required field: {field}")
        return None
    if not isinstance(value, str):
        return _error(action, "invalid_request", f"{field} must be a string.")
    if len(value) > max_len:
        return _error(action, "invalid_request", f"{field} exceeds maximum length {max_len}.")
    if _has_command_tokens(value):
        return _error(action, "invalid_request", f"{field} contains unsupported command-like tokens.")
    return None


def _normalize_entry_path(value: str) -> str:
    return value.replace("\\", "/").lstrip("/")


def _safe_join(base_dir: Path, relative_path: str) -> Path:
    candidate = (base_dir / relative_path).resolve()
    base_resolved = base_dir.resolve()
    if base_resolved not in candidate.parents and candidate != base_resolved:
        raise ValueError("entry_path resolves outside the extraction directory.")
    return candidate


TOOL_ACTION = "extract_zip_artifact_entry"


def main(
    zip_path: str,
    entry_path: str | None = None,
    output_dir: str | None = None,
) -> dict:
    """List or extract files from a ZIP already present in the SRE Agent workspace.

    Use this tool when a ZIP artifact has already been downloaded locally and you
    want to inspect a specific file inside it without sending the entire archive
    through the gateway.

    Modes:
    - List mode: omit entry_path to get the ZIP contents and file sizes.
    - Extract mode: provide entry_path to extract that file to a local directory.
    """
    err = _validate_text(TOOL_ACTION, "zip_path", zip_path, required=True, max_len=1024)
    if err:
        return err
    if entry_path is not None:
        err = _validate_text(TOOL_ACTION, "entry_path", entry_path, required=False, max_len=1024)
        if err:
            return err
    if output_dir is not None:
        err = _validate_text(TOOL_ACTION, "output_dir", output_dir, required=False, max_len=1024)
        if err:
            return err

    zip_file = Path(zip_path).expanduser()
    if not zip_file.exists():
        return _error(TOOL_ACTION, "not_found", f"ZIP file not found: {zip_file}")
    if not zip_file.is_file():
        return _error(TOOL_ACTION, "invalid_request", f"ZIP path is not a file: {zip_file}")

    try:
        with zipfile.ZipFile(zip_file) as archive:
            members = [info for info in archive.infolist() if not info.is_dir()]

            if entry_path is None:
                return _success(
                    TOOL_ACTION,
                    {
                        "zipPath": str(zip_file),
                        "mode": "list",
                        "entryCount": len(members),
                        "entries": [
                            {
                                "path": info.filename,
                                "sizeBytes": info.file_size,
                                "compressedBytes": info.compress_size,
                            }
                            for info in members
                        ],
                    },
                )

            normalized = _normalize_entry_path(entry_path)
            matches = [info for info in members if _normalize_entry_path(info.filename) == normalized]
            if not matches:
                matches = [info for info in members if _normalize_entry_path(info.filename).lower() == normalized.lower()]
            if not matches:
                return _error(
                    TOOL_ACTION,
                    "not_found",
                    f"Entry '{entry_path}' not found in ZIP.",
                    {"zipPath": str(zip_file), "availableEntries": [info.filename for info in members[:50]]},
                )

            member = matches[0]
            target_root = Path(output_dir).expanduser() if output_dir else zip_file.parent / _DEFAULT_OUTPUT_DIR_NAME / zip_file.stem
            target_root.mkdir(parents=True, exist_ok=True)
            extracted_path = _safe_join(target_root, _normalize_entry_path(member.filename))
            extracted_path.parent.mkdir(parents=True, exist_ok=True)

            with archive.open(member, "r") as src, extracted_path.open("wb") as dst:
                dst.write(src.read())

            return _success(
                TOOL_ACTION,
                {
                    "zipPath": str(zip_file),
                    "mode": "extract",
                    "entryPath": member.filename,
                    "outputDir": str(target_root),
                    "extractedPath": str(extracted_path),
                    "sizeBytes": member.file_size,
                    "compressedBytes": member.compress_size,
                },
            )
    except zipfile.BadZipFile as exc:
        return _error(TOOL_ACTION, "invalid_zip", f"Invalid ZIP file: {exc}")
    except Exception as exc:
        return _error(TOOL_ACTION, "io_error", f"Failed to process ZIP file: {exc}")
