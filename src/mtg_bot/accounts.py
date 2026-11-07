"""Player accounts for the Forgetful Fish website.

People register with a user name, a password and the site's invite code, then
log in with the user name and password. Passwords are stored only as salted
scrypt hashes (Werkzeug's ``generate_password_hash``). The accounts live in one
JSON file that is replaced atomically on every change; a lock serializes the
writes inside this process (the website runs as one process).

Failed log-ins are throttled per user name, and wrong invite codes are
throttled for the whole site, so guessing a password or the code is slow. The
throttle state is kept in memory and starts empty when the server restarts.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List

from werkzeug.security import check_password_hash, generate_password_hash

USERNAME_PATTERN = re.compile(r"[A-Za-z0-9_-]{3,24}")
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 200
MAX_FAILED_LOGINS = 8
MAX_FAILED_INVITES = 20
THROTTLE_WINDOW_SECONDS = 15 * 60


class AccountError(ValueError):
    """A registration or log-in that is refused. The message is shown to the user."""


class AccountStore:
    """The accounts in ``path``, registered with ``invite_code``.

    ``clock`` returns seconds and only orders the throttle window; tests pass
    a fake one.
    """

    def __init__(
        self,
        path: Path,
        invite_code: str,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not invite_code:
            raise ValueError("an invite code is required")
        self.path = Path(path)
        self._invite_code = invite_code
        self._clock = clock
        self._lock = threading.Lock()
        self._failed_logins: Dict[str, List[float]] = {}
        self._failed_invites: List[float] = []

    # ------------------------------------------------------------------
    # The accounts file
    # ------------------------------------------------------------------

    def _read_users(self) -> dict:
        if not self.path.exists():
            return {}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return dict(data.get("users", {}))

    def _write_users(self, users: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".accounts-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"users": users}, handle, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    # ------------------------------------------------------------------
    # Registration and log-in
    # ------------------------------------------------------------------

    def register(self, username: str, password: str, invite_code: str) -> str:
        """Create an account and return its user name as typed."""
        name = (username or "").strip()
        if not USERNAME_PATTERN.fullmatch(name):
            raise AccountError("User names are 3-24 letters, digits, '_' or '-'.")
        if not (MIN_PASSWORD_LENGTH <= len(password or "") <= MAX_PASSWORD_LENGTH):
            raise AccountError(
                f"Passwords are {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters long."
            )
        now = self._clock()
        with self._lock:
            self._failed_invites = self._recent(self._failed_invites, now)
            if len(self._failed_invites) >= MAX_FAILED_INVITES:
                raise AccountError("Too many wrong invite codes. Wait 15 minutes and try again.")
            if not hmac.compare_digest(
                (invite_code or "").encode("utf-8"), self._invite_code.encode("utf-8"),
            ):
                self._failed_invites.append(now)
                raise AccountError("That invite code is not right.")
            users = self._read_users()
            key = name.lower()
            if key in users:
                raise AccountError("That user name is taken.")
            users[key] = {
                "username": name,
                "password_hash": generate_password_hash(password),
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            self._write_users(users)
            return name

    def verify(self, username: str, password: str) -> str:
        """The user name as registered when the password is right. An unknown
        user name and a wrong password give the same message."""
        key = (username or "").strip().lower()
        now = self._clock()
        with self._lock:
            recent = self._recent(self._failed_logins.get(key, []), now)
            if len(recent) >= MAX_FAILED_LOGINS:
                self._failed_logins[key] = recent
                raise AccountError(
                    "Too many failed log-ins for this user name. Wait 15 minutes and try again."
                )
            user = self._read_users().get(key)
            if user is None or not check_password_hash(user["password_hash"], password or ""):
                recent.append(now)
                self._failed_logins[key] = recent
                raise AccountError("Wrong user name or password.")
            self._failed_logins.pop(key, None)
            return user["username"]

    def _recent(self, stamps: List[float], now: float) -> List[float]:
        return [stamp for stamp in stamps if now - stamp < THROTTLE_WINDOW_SECONDS]
