"""Small, process-safe state primitives shared by the runner and local review UI."""

import json
import math
import os
from pathlib import Path
import tempfile
import time
import uuid


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as stream:
            return json.load(stream)
    except FileNotFoundError:
        return default


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Serialize before opening a temporary file: invalid numbers must not enter the ledger.
    content = json.dumps(data, indent=2, allow_nan=False) + "\n"
    handle, temporary = tempfile.mkstemp(prefix=".state-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class FileLock:
    """An OS lock, released on process death; the stable lock file is never unlinked."""

    def __init__(self, path, timeout=10):
        self.path = Path(path)
        self.timeout = timeout
        self.stream = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = open(self.path, "a+b")
        self.stream.seek(0, os.SEEK_END)
        if not self.stream.tell():
            self.stream.write(b"\0")
            self.stream.flush()
        started = time.monotonic()
        while True:
            try:
                self.stream.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except (OSError, BlockingIOError):
                if time.monotonic() - started >= self.timeout:
                    self.stream.close()
                    self.stream = None
                    raise TimeoutError(f"Another process holds {self.path.name}") from None
                time.sleep(0.05)

    def __exit__(self, *_):
        if self.stream is not None:
            self.stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
            self.stream.close()
            self.stream = None


def append_event(path, data):
    path = Path(path)
    with FileLock(str(path) + ".lock"):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(data, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())


class BudgetExceeded(RuntimeError):
    pass


def _amount(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite nonnegative number")
    return float(value)


class BudgetLedger:
    """Reserve before calls. Unknown charges consume the reservation, including failed calls.

    This is a conservative accounting allowance, not a provider-enforced dollar cap.
    Actual reported charges are never truncated to the reservation.
    """

    def __init__(self, path, limit):
        self.path = Path(path)
        self.limit = _amount(limit, "limit")
        with FileLock(str(self.path) + ".lock"):
            state = read_json(self.path)
            if state is None:
                atomic_json(self.path, {"version": 1, "limit": self.limit, "reservations": {}})
            elif state.get("limit") != self.limit:
                raise ValueError("Existing run budget differs; resume must preserve its original allowance")

    def _read(self):
        state = read_json(self.path)
        if not isinstance(state, dict) or state.get("version") != 1 or not isinstance(state.get("reservations"), dict):
            raise ValueError("Invalid budget ledger; refusing to reset spending")
        return state

    def snapshot(self):
        with FileLock(str(self.path) + ".lock"):
            state = self._read()
            reservations = state["reservations"]
            spent = sum(r["charged"] for r in reservations.values() if r["status"] == "settled")
            reserved = sum(r["amount"] for r in reservations.values() if r["status"] == "reserved")
            reported = sum(
                r["charged"] for r in reservations.values() if r["status"] == "settled" and r.get("cost_known")
            )
            return {
                **state,
                "spent": round(spent, 8),
                "reported_cost": round(reported, 8),
                "reserved": round(reserved, 8),
                "remaining": max(0.0, round(state["limit"] - spent - reserved, 8)),
                "calls": len(reservations),
                "unsettled_calls": sum(r["status"] == "reserved" for r in reservations.values()),
            }

    @property
    def remaining(self):
        return self.snapshot()["remaining"]

    @property
    def spent(self):
        return self.snapshot()["spent"]

    def reserve(self, amount, label):
        amount = _amount(amount, "reservation")
        if amount == 0:
            raise ValueError("A model call requires a positive reservation")
        with FileLock(str(self.path) + ".lock"):
            state = self._read()
            consumed = sum(
                r["charged"] if r["status"] == "settled" else r["amount"] for r in state["reservations"].values()
            )
            if consumed + amount > state["limit"] + 1e-9:
                raise BudgetExceeded("Insufficient remaining run allowance")
            reservation = uuid.uuid4().hex
            state["reservations"][reservation] = {
                "amount": amount,
                "label": str(label)[:200],
                "status": "reserved",
                "created": time.time(),
            }
            atomic_json(self.path, state)
            return reservation

    def settle(self, reservation, cost=None, usage=None):
        if cost is not None:
            cost = _amount(cost, "cost")
        with FileLock(str(self.path) + ".lock"):
            state = self._read()
            entry = state["reservations"][reservation]
            charge = entry["amount"] if cost is None else cost
            if entry["status"] == "settled":
                if entry["charged"] != charge or entry["cost_known"] != (cost is not None):
                    raise ValueError("Reservation already settled with different usage")
                return entry["charged"]
            entry.update(
                status="settled", charged=charge, cost_known=cost is not None, usage=usage or {}, settled=time.time()
            )
            atomic_json(self.path, state)
            return charge


def paused(root):
    control = read_json(Path(root) / "runs" / "control.json", {})
    if not isinstance(control, dict) or not isinstance(control.get("paused", False), bool):
        raise ValueError("Invalid research control state")
    return control.get("paused", False)
