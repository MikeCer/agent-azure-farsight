from __future__ import annotations

from collections.abc import Callable
from email.utils import parsedate_to_datetime
from time import sleep
from typing import Any
import base64
import binascii
import datetime as dt
import json as json_module
import sys

import requests


class GraphError(RuntimeError):
    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        url: str | None = None,
        *,
        error_code: str | None = None,
        response_body: object | None = None,
        identity_context: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.url = url
        self.error_code = error_code
        self.response_body = response_body
        self.identity_context = identity_context or {}


class GraphClient:
    def __init__(
        self,
        token_provider: Callable[[], str],
        *,
        base_url: str = "https://graph.microsoft.com",
        timeout_seconds: int = 30,
        max_retries: int = 3,
        session: requests.Session | None = None,
    ) -> None:
        self._token_provider = token_provider
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._session = session or requests.Session()

    def get(self, api_version: str, path_or_url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request("GET", api_version, path_or_url, params=params)

    def post(
        self,
        api_version: str,
        path_or_url: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.request("POST", api_version, path_or_url, json=payload or {})

    def request(
        self,
        method: str,
        api_version: str,
        path_or_url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = self._url(api_version, path_or_url)
        for attempt in range(self._max_retries + 1):
            token = self._token_provider()
            response = self._session.request(
                method,
                url,
                params=params,
                json=json,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=self._timeout_seconds,
            )
            if response.status_code in {429, 500, 502, 503, 504} and attempt < self._max_retries:
                sleep(self._retry_after_seconds(response.headers.get("Retry-After"), attempt))
                continue
            if response.status_code >= 400:
                message, error_code, response_body = self._error_details(response)
                identity_context = self._token_identity_context(token)
                self._log_graph_error_identity(response, identity_context)
                raise GraphError(
                    message,
                    response.status_code,
                    response.url,
                    error_code=error_code,
                    response_body=response_body,
                    identity_context=identity_context,
                )
            if not response.content:
                return {}
            return response.json()
        raise GraphError(f"Microsoft Graph request failed after {self._max_retries + 1} attempts", url=url)

    def get_all(
        self,
        api_version: str,
        path_or_url: str,
        *,
        params: dict[str, Any] | None = None,
        max_pages: int | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        items: list[dict[str, Any]] = []
        next_url: str | None = path_or_url
        page = 0
        followed_next_link = False
        while next_url:
            if max_pages is not None and page >= max_pages:
                raise GraphError(f"Page limit of {max_pages} reached while reading {path_or_url}")
            data = self.get(api_version, next_url, params=params if page == 0 else None)
            value = data.get("value")
            if isinstance(value, list):
                items.extend(value)
            else:
                items.append(data)
            next_url = data.get("@odata.nextLink")
            followed_next_link = followed_next_link or bool(next_url)
            params = None
            page += 1
        return items, followed_next_link

    def _url(self, api_version: str, path_or_url: str) -> str:
        if path_or_url.startswith("https://"):
            return path_or_url
        path = path_or_url if path_or_url.startswith("/") else f"/{path_or_url}"
        return f"{self._base_url}/{api_version}{path}"

    @staticmethod
    def _token_identity_context(token: str) -> dict[str, Any]:
        claims = GraphClient._decode_jwt_claims(token)
        if not claims:
            return {}
        return {
            key: value
            for key, value in {
                "tenant_id": claims.get("tid"),
                "object_id": claims.get("oid") or claims.get("sub"),
                "app_id": claims.get("appid") or claims.get("azp"),
                "user": claims.get("preferred_username") or claims.get("upn") or claims.get("unique_name"),
                "identity_type": claims.get("idtyp"),
            }.items()
            if value not in (None, "")
        }

    @staticmethod
    def _decode_jwt_claims(token: str) -> dict[str, Any]:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1]
        padding = "=" * (-len(payload) % 4)
        try:
            decoded = base64.urlsafe_b64decode((payload + padding).encode("ascii"))
            claims = json_module.loads(decoded.decode("utf-8"))
        except (binascii.Error, ValueError, json_module.JSONDecodeError, UnicodeDecodeError):
            return {}
        return claims if isinstance(claims, dict) else {}

    @staticmethod
    def _log_graph_error_identity(response: requests.Response, identity_context: dict[str, Any]) -> None:
        if identity_context:
            identity = ", ".join(f"{key}={value}" for key, value in identity_context.items())
        else:
            identity = "unavailable"
        print(
            f"Microsoft Graph request failed: method={getattr(getattr(response, 'request', None), 'method', 'unknown')} "
            f"status={response.status_code} url={response.url} identity={identity}",
            file=sys.stderr,
        )

    @staticmethod
    def _retry_after_seconds(value: str | None, attempt: int) -> float:
        if not value:
            return min(2**attempt, 10)
        try:
            return float(value)
        except ValueError:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=dt.timezone.utc)
            return max(0.0, (retry_at - dt.datetime.now(dt.timezone.utc)).total_seconds())

    @staticmethod
    def _error_message(response: requests.Response) -> str:
        message, _, _ = GraphClient._error_details(response)
        return message

    @staticmethod
    def _error_details(response: requests.Response) -> tuple[str, str | None, object | None]:
        try:
            body = response.json()
        except ValueError:
            return f"Microsoft Graph returned HTTP {response.status_code}: {response.text}", None, response.text
        error = body.get("error") if isinstance(body, dict) else None
        code = error.get("code") if isinstance(error, dict) else body.get("ErrorCode") if isinstance(body, dict) else None
        message = error.get("message") if isinstance(error, dict) else None
        if not message and isinstance(body, dict):
            message = body.get("Message") or body.get("error_description")
        return f"Microsoft Graph returned HTTP {response.status_code}: {message or body}", code, body
