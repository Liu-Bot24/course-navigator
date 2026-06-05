from __future__ import annotations

import json
import re
from collections.abc import Iterable

DEFAULT_COOKIE_DOMAIN = ".youtube.com"
NETSCAPE_HEADER = "# Netscape HTTP Cookie File"
IGNORED_COOKIE_ATTRIBUTES = {
    "domain",
    "expires",
    "httponly",
    "max-age",
    "path",
    "samesite",
    "secure",
}


def normalize_cookie_text(raw_text: str) -> str:
    text = raw_text.strip()
    if not text:
        raise ValueError("Cookie 内容为空")

    normalizers = (
        _normalize_netscape_cookie_text,
        _normalize_json_cookie_text,
        _normalize_header_cookie_text,
    )
    for normalize in normalizers:
        normalized = normalize(text)
        if normalized:
            return normalized
    raise ValueError("没有解析到可用 Cookie")


def _normalize_netscape_cookie_text(text: str) -> str | None:
    rows = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t", 6)
        if len(fields) == 7 and fields[0] and fields[2] and fields[5]:
            rows.append("\t".join(_clean_cookie_field(field) for field in fields))
    return _format_netscape_rows(rows)


def _normalize_json_cookie_text(text: str) -> str | None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None

    if isinstance(payload, dict) and isinstance(payload.get("cookies"), list):
        cookie_entries = payload["cookies"]
    elif isinstance(payload, dict) and "name" in payload and "value" in payload:
        cookie_entries = [payload]
    elif isinstance(payload, dict):
        cookie_entries = [
            {"name": key, "value": value}
            for key, value in payload.items()
            if isinstance(key, str) and isinstance(value, (str, int, float, bool))
        ]
    elif isinstance(payload, list):
        cookie_entries = payload
    else:
        return None

    rows = []
    for entry in cookie_entries:
        if not isinstance(entry, dict):
            continue
        row = _netscape_row_from_mapping(entry)
        if row:
            rows.append(row)
    return _format_netscape_rows(rows)


def _normalize_header_cookie_text(text: str) -> str | None:
    match = re.search(r"\bcookie\s*:\s*([^\r\n]+)", text, flags=re.IGNORECASE)
    header = match.group(1) if match else text
    header = header.strip().strip("\"'")
    if "=" not in header:
        return None

    rows = []
    for part in header.split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        if not name or name.lower() in IGNORED_COOKIE_ATTRIBUTES:
            continue
        rows.append(
            _netscape_row(
                domain=DEFAULT_COOKIE_DOMAIN,
                include_subdomains=True,
                path="/",
                secure=True,
                expires=0,
                name=name,
                value=value.strip().strip("\"'"),
            )
        )
    return _format_netscape_rows(rows)


def _netscape_row_from_mapping(entry: dict[object, object]) -> str | None:
    name = _string_value(entry.get("name"))
    value = _string_value(entry.get("value"))
    if not name or value is None:
        return None
    domain = _string_value(entry.get("domain")) or DEFAULT_COOKIE_DOMAIN
    path = _string_value(entry.get("path")) or "/"
    secure = bool(entry.get("secure", True))
    expires = _expiry_value(
        entry.get("expirationDate"),
        entry.get("expiry"),
        entry.get("expires"),
        entry.get("expiration"),
    )
    return _netscape_row(
        domain=domain,
        include_subdomains=domain.startswith("."),
        path=path,
        secure=secure,
        expires=expires,
        name=name,
        value=value,
    )


def _expiry_value(*candidates: object) -> int:
    for candidate in candidates:
        if candidate in (None, "") or isinstance(candidate, bool):
            continue
        try:
            return max(0, int(float(str(candidate))))
        except ValueError:
            continue
    return 0


def _string_value(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _netscape_row(
    *,
    domain: str,
    include_subdomains: bool,
    path: str,
    secure: bool,
    expires: int,
    name: str,
    value: str,
) -> str:
    return "\t".join(
        (
            _clean_cookie_field(domain),
            "TRUE" if include_subdomains else "FALSE",
            _clean_cookie_field(path or "/"),
            "TRUE" if secure else "FALSE",
            str(expires),
            _clean_cookie_field(name),
            _clean_cookie_field(value),
        )
    )


def _format_netscape_rows(rows: Iterable[str]) -> str | None:
    unique_rows = list(dict.fromkeys(row for row in rows if row))
    if not unique_rows:
        return None
    return "\n".join((NETSCAPE_HEADER, *unique_rows, ""))


def _clean_cookie_field(value: object) -> str:
    return str(value).replace("\r", "").replace("\n", "").replace("\t", " ").strip()
