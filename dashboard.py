"""Local research review dashboard.

Run with ``python dashboard.py`` and open http://localhost:8766. The server only
binds to loopback. Approval records are local, immutable hash bindings; this
module never invokes publishing or another outbound action.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import tempfile
from typing import Any
from urllib.parse import urlsplit
import webbrowser

from research_state import FileLock, atomic_json, read_json


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
MAX_BODY_BYTES = 16 * 1024
MAX_EVIDENCE_BYTES = 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
EVIDENCE_PATH_RE = re.compile(r"^runs/research/[^/]+/[^/]+/evidence\.json$")
FAILURE_STATUSES = {"failed", "error", "rejected", "cancelled", "canceled", "incomplete"}
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _strict_object(raw: bytes) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"Unsupported JSON number: {value}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), parse_constant=reject_constant, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, "invalid_json", "Request body must be one valid JSON object.") from exc
    if not isinstance(value, dict):
        raise ApiError(HTTPStatus.BAD_REQUEST, "invalid_payload", "Request body must be a JSON object.")
    return value


def _expect_keys(value: dict[str, Any], required: set[str], optional: set[str] | None = None) -> None:
    optional = optional or set()
    if set(value) - required - optional or not required.issubset(value):
        raise ApiError(HTTPStatus.BAD_REQUEST, "invalid_payload", "Request fields do not match this endpoint.")


def _number(value: Any, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ApiError(HTTPStatus.BAD_REQUEST, "invalid_payload", f"{name} must be a finite number.")
    number = float(value)
    if number < minimum or number > maximum:
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "invalid_payload",
            f"{name} must be between {minimum:g} and {maximum:g}.",
        )
    return number


def _relative_path(value: Any, *, evidence: bool = False) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ApiError(HTTPStatus.BAD_REQUEST, "invalid_payload", "Artifact paths must be repo-relative POSIX paths.")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts) or path.as_posix() != value:
        raise ApiError(HTTPStatus.BAD_REQUEST, "invalid_payload", "Artifact paths must be repo-relative POSIX paths.")
    if evidence and not EVIDENCE_PATH_RE.fullmatch(value):
        raise ApiError(
            HTTPStatus.BAD_REQUEST, "invalid_payload", "Evidence path is outside the research evidence layout."
        )
    return value


def _path_without_symlinks(root: Path, relative: str) -> Path:
    path = root
    for part in PurePosixPath(relative).parts:
        path = path / part
        if path.is_symlink():
            raise ApiError(HTTPStatus.BAD_REQUEST, "invalid_payload", "Symbolic links cannot be approved.")
    try:
        resolved = path.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, "invalid_payload", "The selected artifact no longer exists.") from exc
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, "invalid_payload", "Artifact path leaves the repository.") from exc
    if not resolved.is_file():
        raise ApiError(HTTPStatus.BAD_REQUEST, "invalid_payload", "The selected artifact is not a regular file.")
    return resolved


def _stable_bytes(path: Path, maximum: int | None = None) -> bytes:
    try:
        before = path.stat()
        if maximum is not None and before.st_size > maximum:
            raise ApiError(
                HTTPStatus.BAD_REQUEST, "invalid_payload", "Artifact is too large to review in the dashboard."
            )
        data = path.read_bytes()
        after = path.stat()
    except ApiError:
        raise
    except OSError as exc:
        raise ApiError(HTTPStatus.CONFLICT, "artifact_changed", "Artifact changed while it was being checked.") from exc
    before_key = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    after_key = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if before_key != after_key or len(data) != after.st_size:
        raise ApiError(HTTPStatus.CONFLICT, "artifact_changed", "Artifact changed while it was being checked.")
    return data


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_read(path: Path, default: Any) -> Any:
    try:
        return read_json(path, default)
    except (OSError, ValueError, TypeError):
        return default


def _trial_summary(root: Path) -> dict[str, Any]:
    try:
        from trial_report import summarize

        result = summarize(root)
        if isinstance(result, dict) and isinstance(result.get("rows"), list):
            return result
    except (ImportError, OSError, TypeError, ValueError):
        pass
    return {
        "rows": [],
        "runs": 0,
        "unreadable": 0,
        "note": "The 14-night comparison has not started.",
    }


def _sanitize(value: Any, root: Path, depth: int = 0) -> Any:
    if depth > 8:
        return "[detail omitted]"
    if isinstance(value, dict):
        return {str(key)[:120]: _sanitize(item, root, depth + 1) for key, item in list(value.items())[:250]}
    if isinstance(value, list):
        return [_sanitize(item, root, depth + 1) for item in value[:500]]
    if isinstance(value, str):
        if len(value) > 20_000:
            return value[:20_000] + "…"
        candidate = Path(value)
        if candidate.is_absolute():
            try:
                return candidate.resolve().relative_to(root.resolve()).as_posix()
            except (OSError, ValueError):
                return "[external path omitted]"
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)[:500]


class DashboardApp:
    def __init__(self, root: Path, csrf_token: str | None = None, web_root: Path = WEB_ROOT):
        self.root = Path(root).resolve()
        self.web_root = Path(web_root).resolve()
        self.csrf_token = csrf_token or secrets.token_urlsafe(32)
        self.runs = self.root / "runs"
        self.control_path = self.runs / "control.json"
        self.schedule_path = self.root / "night.json"
        self.night_status_path = self.runs / "night-status.json"
        self.approvals = self.runs / "research" / "approvals"

    def legacy_runs(self) -> list[dict[str, Any]]:
        result = []
        for directory in sorted(self.root.glob("runs*")):
            log = directory / "log.jsonl"
            if not directory.is_dir() or not log.is_file():
                continue
            problem = "circle_packing" if directory.name == "runs" else directory.name.removeprefix("runs-")
            iterations = champions = 0
            wins: set[str] = set()
            try:
                with log.open(encoding="utf-8") as stream:
                    for line in stream:
                        try:
                            row = json.loads(line)
                        except (json.JSONDecodeError, TypeError):
                            continue
                        if not isinstance(row, dict):
                            continue
                        iterations += 1
                        champions += row.get("status") == "champion"
                        if isinstance(row.get("wins"), list):
                            wins.update(str(item) for item in row["wins"])
            except OSError:
                continue
            result.append(
                {
                    "problem": problem,
                    "iterations": iterations,
                    "champions": champions,
                    "wins": len(wins),
                    "classification": "historical_unvalidated",
                }
            )
        return result

    def schedule_summary(self) -> dict[str, Any]:
        schedule = _safe_read(self.schedule_path, {})
        night = schedule.get("night", {}) if isinstance(schedule, dict) else {}
        caps = night.get("provider_caps_usd", {}) if isinstance(night, dict) else {}
        return {
            "duration_minutes": night.get("deadline_minutes", 480),
            "nightly_budget_usd": night.get("budget_usd", 90),
            "provider_caps_usd": {
                "fable": caps.get("fable", 20),
                "astra": caps.get("astra", 20),
                "paired": caps.get("paired", 20),
            },
        }

    def status(self) -> dict[str, Any]:
        control = _safe_read(self.control_path, {})
        if not isinstance(control, dict):
            control = {}
        control = {**control, "paused": control.get("paused", False) is True}
        night_status = _safe_read(self.night_status_path, {})
        if not isinstance(night_status, dict):
            night_status = {"status": "unavailable"}
        return {
            "generated_at": _utc_now(),
            "csrf_token": self.csrf_token,
            "control": _sanitize(control, self.root),
            "night_status": _sanitize(night_status, self.root),
            "schedule": self.schedule_summary(),
            "legacy": self.legacy_runs(),
            "trial": _sanitize(_trial_summary(self.root), self.root),
        }

    def evidence(self) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        research = self.runs / "research"
        paths = sorted(research.glob("*/*/evidence.json"), key=lambda item: item.stat().st_mtime_ns, reverse=True)
        for path in paths[:200]:
            try:
                relative = path.relative_to(self.root).as_posix()
                raw_bytes = _stable_bytes(path, MAX_EVIDENCE_BYTES)
                data = json.loads(raw_bytes.decode("utf-8"))
                if not isinstance(data, dict):
                    continue
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, ApiError):
                continue
            normalized = {
                "run_id": data.get("run_id", path.parent.parent.name),
                "problem": data.get("problem", path.parent.name),
                "provider": data.get("provider", "unknown"),
                "status": data.get("status", "unknown"),
                "confirmed": data.get("confirmed") is True,
                "publishable": data.get("publishable") is True,
                "candidate_path": data.get("candidate_path"),
                "candidate_hash": data.get("candidate_hash"),
                "development": data.get("development", {}),
                "confirmation": data.get("confirmation", {}),
                "usage": data.get("usage", {}),
                "limitations": data.get("limitations", []),
                "started_at": data.get("started_at"),
                "finished_at": data.get("finished_at"),
                "evidence_path": relative,
                "evidence_hash": _digest(raw_bytes),
                "classification": "confirmed" if data.get("confirmed") is True else "unvalidated",
                "raw": _sanitize(data, self.root),
            }
            items.append(_sanitize(normalized, self.root))
        return {"generated_at": _utc_now(), "evidence": items}

    def update_control(self, payload: dict[str, Any]) -> dict[str, Any]:
        _expect_keys(payload, {"action"}, {"evidence_path"})
        action = payload.get("action")
        if action not in {"pause", "continue", "request_review"}:
            raise ApiError(HTTPStatus.BAD_REQUEST, "invalid_payload", "Action must pause, continue, or request review.")
        if action == "request_review":
            _expect_keys(payload, {"action", "evidence_path"})
            evidence_path = _relative_path(payload["evidence_path"], evidence=True)
        elif "evidence_path" in payload:
            raise ApiError(
                HTTPStatus.BAD_REQUEST, "invalid_payload", "Evidence path is only valid for a review request."
            )
        with FileLock(str(self.control_path) + ".lock"):
            control = _safe_read(self.control_path, {})
            if not isinstance(control, dict):
                raise ApiError(HTTPStatus.CONFLICT, "invalid_state", "Research control state is not a JSON object.")
            if action == "pause":
                control["paused"] = True
            elif action == "continue":
                control["paused"] = False
            else:
                control["review_request"] = {"evidence_path": evidence_path, "requested_at": _utc_now()}
            control["updated_at"] = _utc_now()
            atomic_json(self.control_path, control)
        return {"control": _sanitize(control, self.root)}

    def update_schedule(self, payload: dict[str, Any]) -> dict[str, Any]:
        required = {"duration_minutes", "nightly_budget_usd", "provider_caps_usd"}
        _expect_keys(payload, required)
        duration = payload["duration_minutes"]
        if isinstance(duration, bool) or not isinstance(duration, int) or not 60 <= duration <= 720:
            raise ApiError(HTTPStatus.BAD_REQUEST, "invalid_payload", "Duration must be a whole number from 60 to 720.")
        budget = _number(payload["nightly_budget_usd"], "Nightly research allowance", 0, 90)
        if budget <= 0:
            raise ApiError(
                HTTPStatus.BAD_REQUEST, "invalid_payload", "Nightly research allowance must be greater than zero."
            )
        caps = payload["provider_caps_usd"]
        if not isinstance(caps, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "invalid_payload", "Provider caps must be a JSON object.")
        _expect_keys(caps, {"fable", "astra", "paired"})
        clean_caps = {name: _number(caps[name], f"{name} allowance", 0, 90) for name in ("fable", "astra", "paired")}
        lock = str(self.schedule_path) + ".lock"
        with FileLock(lock):
            schedule = _safe_read(self.schedule_path, None)
            if not isinstance(schedule, dict) or not isinstance(schedule.get("night"), dict):
                raise ApiError(HTTPStatus.CONFLICT, "invalid_state", "The v2 night schedule is unavailable.")
            schedule["night"]["deadline_minutes"] = duration
            schedule["night"]["budget_usd"] = budget
            schedule["night"]["provider_caps_usd"] = clean_caps
            slots = schedule.get("slots")
            if not isinstance(slots, list):
                raise ApiError(HTTPStatus.CONFLICT, "invalid_state", "The night schedule has no slot list.")
            configured = sum(
                float(slot.get("slot_budget_usd", 0)) + float(slot.get("retro_budget_usd", 0))
                for slot in slots
                if isinstance(slot, dict)
            )
            if configured > budget:
                scale = budget / configured
                for slot in slots:
                    if not isinstance(slot, dict):
                        continue
                    slot["slot_budget_usd"] = float(slot.get("slot_budget_usd", 0)) * scale
                    slot["retro_budget_usd"] = float(slot.get("retro_budget_usd", 0)) * scale
                    if slot.get("kind") == "research":
                        slot["per_call_budget_usd"] = min(
                            float(slot.get("per_call_budget_usd", 0)), slot["slot_budget_usd"]
                        )
            configured_minutes = sum(float(slot.get("minutes", 0)) for slot in slots if isinstance(slot, dict))
            if configured_minutes > duration:
                scale = duration / configured_minutes
                for slot in slots:
                    if not isinstance(slot, dict):
                        continue
                    slot["minutes"] = float(slot.get("minutes", 0)) * scale
                    if slot.get("kind") == "research":
                        slot["research_minutes"] = float(slot.get("research_minutes", 0)) * scale
                        slot["retro_minutes"] = float(slot.get("retro_minutes", 0)) * scale
            handle, validation_name = tempfile.mkstemp(
                prefix=".dashboard-validation-", suffix=".json", dir=self.schedule_path.parent
            )
            os.close(handle)
            Path(validation_name).unlink(missing_ok=True)
            try:
                atomic_json(validation_name, schedule)
                from night import load_schedule

                load_schedule(validation_name)
            except (OSError, TypeError, ValueError) as exc:
                raise ApiError(
                    HTTPStatus.CONFLICT,
                    "invalid_state",
                    "The updated settings do not form a valid night schedule.",
                ) from exc
            finally:
                try:
                    Path(validation_name).unlink(missing_ok=True)
                except OSError:
                    pass
            atomic_json(self.schedule_path, schedule)
        return {
            "schedule": {
                "duration_minutes": duration,
                "nightly_budget_usd": budget,
                "provider_caps_usd": clean_caps,
            }
        }

    def approve(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        required = {"evidence_path", "evidence_hash", "candidate_path", "candidate_hash", "confirmed"}
        _expect_keys(payload, required)
        if payload["confirmed"] is not True:
            raise ApiError(HTTPStatus.BAD_REQUEST, "invalid_payload", "Explicit review confirmation is required.")
        evidence_relative = _relative_path(payload["evidence_path"], evidence=True)
        candidate_relative = _relative_path(payload["candidate_path"])
        supplied_evidence_hash = payload["evidence_hash"]
        supplied_candidate_hash = payload["candidate_hash"]
        if not isinstance(supplied_evidence_hash, str) or not SHA256_RE.fullmatch(supplied_evidence_hash):
            raise ApiError(
                HTTPStatus.BAD_REQUEST, "invalid_payload", "Evidence hash must be a lowercase SHA-256 digest."
            )
        if not isinstance(supplied_candidate_hash, str) or not SHA256_RE.fullmatch(supplied_candidate_hash):
            raise ApiError(
                HTTPStatus.BAD_REQUEST, "invalid_payload", "Candidate hash must be a lowercase SHA-256 digest."
            )
        evidence_path = _path_without_symlinks(self.root, evidence_relative)
        candidate_path = _path_without_symlinks(self.root, candidate_relative)
        approvals_relative = self.approvals.relative_to(self.root).as_posix() + "/"
        if candidate_relative.startswith(approvals_relative) or candidate_relative == evidence_relative:
            raise ApiError(
                HTTPStatus.BAD_REQUEST, "invalid_payload", "Approval storage and evidence cannot be candidates."
            )

        approval_path = self.approvals / f"{supplied_candidate_hash}.json"
        with FileLock(self.runs / "research" / ".approvals.lock"):
            evidence_bytes = _stable_bytes(evidence_path, MAX_EVIDENCE_BYTES)
            candidate_bytes = _stable_bytes(candidate_path)
            evidence_hash = _digest(evidence_bytes)
            candidate_hash = _digest(candidate_bytes)
            if evidence_hash != supplied_evidence_hash or candidate_hash != supplied_candidate_hash:
                raise ApiError(
                    HTTPStatus.CONFLICT, "artifact_changed", "Candidate or evidence changed. Refresh before approving."
                )
            try:
                evidence = json.loads(evidence_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ApiError(HTTPStatus.CONFLICT, "artifact_changed", "Evidence is no longer valid JSON.") from exc
            if not isinstance(evidence, dict):
                raise ApiError(HTTPStatus.BAD_REQUEST, "invalid_payload", "Evidence must be a JSON object.")
            if evidence.get("confirmed") is not True or evidence.get("publishable") is not True:
                raise ApiError(
                    HTTPStatus.CONFLICT, "evidence_not_publishable", "Evidence is not confirmed and publishable."
                )
            if str(evidence.get("status", "")).lower() in FAILURE_STATUSES:
                raise ApiError(HTTPStatus.CONFLICT, "evidence_not_publishable", "Failed evidence cannot be approved.")
            if evidence.get("candidate_path") != candidate_relative or evidence.get("candidate_hash") != candidate_hash:
                raise ApiError(
                    HTTPStatus.CONFLICT, "artifact_changed", "Candidate does not match the selected evidence."
                )
            approval = {
                "approved": True,
                "approved_at": _utc_now(),
                "evidence_path": evidence_relative,
                "evidence_hash": evidence_hash,
                "candidate_path": candidate_relative,
                "candidate_hash": candidate_hash,
            }
            existing = _safe_read(approval_path, None)
            if existing is not None:
                comparable = (
                    {key: existing.get(key) for key in approval if key != "approved_at"}
                    if isinstance(existing, dict)
                    else {}
                )
                expected = {key: value for key, value in approval.items() if key != "approved_at"}
                if comparable != expected:
                    raise ApiError(
                        HTTPStatus.CONFLICT, "approval_exists", "A different approval already uses this hash."
                    )
                approval = existing
                status = HTTPStatus.OK
            else:
                self.approvals.mkdir(parents=True, exist_ok=True)
                atomic_json(approval_path, approval)
                status = HTTPStatus.CREATED
        return status, {
            "approval": approval,
            "message": "Approval queued locally. No publication occurred.",
        }


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _handler(app: DashboardApp):
    class Handler(BaseHTTPRequestHandler):
        server_version = "DiscoveryDashboard/1"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _security_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; connect-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
            )
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")

        def _json(self, status: int, data: dict[str, Any]) -> None:
            body = json.dumps(data, allow_nan=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._security_headers()
            self.end_headers()
            self.wfile.write(body)

        def _error(self, error: ApiError) -> None:
            self._json(error.status, {"error": error.code, "message": error.message})

        def _host(self) -> tuple[str, int]:
            raw = self.headers.get("Host", "").lower()
            server_port = self.server.server_address[1]
            allowed = {f"localhost:{server_port}", f"127.0.0.1:{server_port}", f"[::1]:{server_port}"}
            if raw not in allowed:
                raise ApiError(HTTPStatus.FORBIDDEN, "untrusted_host", "Host must be this local dashboard.")
            parsed = urlsplit("//" + raw)
            return (parsed.hostname or "").lower(), server_port

        def _check_origin_and_csrf(self) -> None:
            self._host()
            origin = self.headers.get("Origin")
            if not origin:
                raise ApiError(
                    HTTPStatus.FORBIDDEN, "same_origin_required", "A same-origin browser request is required."
                )
            expected_origin = f"http://{self.headers.get('Host', '').lower()}"
            if origin.lower() != expected_origin:
                raise ApiError(
                    HTTPStatus.FORBIDDEN, "same_origin_required", "A same-origin browser request is required."
                )
            if not secrets.compare_digest(self.headers.get("X-CSRF-Token", ""), app.csrf_token):
                raise ApiError(HTTPStatus.FORBIDDEN, "csrf_failed", "Refresh the dashboard before trying again.")

        def _payload(self) -> dict[str, Any]:
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                raise ApiError(
                    HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "json_required", "Content-Type must be application/json."
                )
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError as exc:
                raise ApiError(
                    HTTPStatus.LENGTH_REQUIRED, "content_length_required", "Content-Length is required."
                ) from exc
            if length < 0:
                raise ApiError(HTTPStatus.BAD_REQUEST, "invalid_payload", "Content-Length cannot be negative.")
            if length > MAX_BODY_BYTES:
                raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "body_too_large", "Request body exceeds 16 KiB.")
            return _strict_object(self.rfile.read(length))

        def do_GET(self) -> None:
            try:
                self._host()
                path = urlsplit(self.path).path
                if path == "/api/status":
                    self._json(HTTPStatus.OK, app.status())
                elif path == "/api/evidence":
                    self._json(HTTPStatus.OK, app.evidence())
                elif path in STATIC_FILES:
                    filename, content_type = STATIC_FILES[path]
                    target = app.web_root / filename
                    try:
                        body = target.read_bytes()
                    except OSError as exc:
                        raise ApiError(HTTPStatus.NOT_FOUND, "not_found", "Dashboard asset not found.") from exc
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(body)))
                    self._security_headers()
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    raise ApiError(HTTPStatus.NOT_FOUND, "not_found", "Route not found.")
            except ApiError as error:
                self._error(error)

        def do_POST(self) -> None:
            try:
                self._check_origin_and_csrf()
                path = urlsplit(self.path).path
                payload = self._payload()
                if path == "/api/control":
                    result = app.update_control(payload)
                    self._json(HTTPStatus.OK, result)
                elif path == "/api/schedule":
                    result = app.update_schedule(payload)
                    self._json(HTTPStatus.OK, result)
                elif path == "/api/approve":
                    status, result = app.approve(payload)
                    self._json(status, result)
                else:
                    raise ApiError(HTTPStatus.NOT_FOUND, "not_found", "Route not found.")
            except ApiError as error:
                self._error(error)

    return Handler


def create_server(root: Path | str = ROOT, host: str = "127.0.0.1", port: int = 8766, csrf_token: str | None = None):
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Dashboard may only bind to loopback")
    app = DashboardApp(Path(root), csrf_token=csrf_token)
    return DashboardServer((host, port), _handler(app))


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the local discovery research review dashboard")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--open", action="store_true", help="open the local dashboard in the default browser")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    server = create_server(port=args.port)
    url = f"http://localhost:{server.server_address[1]}"
    print(f"Discovery review: {url}", flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
