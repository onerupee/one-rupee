"""Installation identity and optional local activation helpers."""

import hashlib
import json
import uuid
from pathlib import Path

DATA_DIR = Path.home() / ".one_rupee"
ACTIVATION_FILE = DATA_DIR / ".one_rupee_activation.json"
# Keep identity in per-user data, never in the distributable package.
INSTALLATION_MARKER = DATA_DIR / ".installation_id"


def get_installation_id():
    """Return a stable per-user installation ID outside the package directory.

    The ID is created atomically in the user's data directory. This prevents a
    marker baked into a wheel/source ZIP from being shared by every installer.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        value = INSTALLATION_MARKER.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        value = ""

    if value.startswith("one_rupee_install_") and len(value) == 50:
        return value

    installation_id = "one_rupee_install_" + uuid.uuid4().hex
    try:
        # Exclusive creation avoids two simultaneous processes replacing each
        # other's newly generated identity.
        with INSTALLATION_MARKER.open("x", encoding="utf-8") as marker:
            marker.write(installation_id + "\n")
        return installation_id
    except FileExistsError:
        value = INSTALLATION_MARKER.read_text(encoding="utf-8").strip()
        if value.startswith("one_rupee_install_") and len(value) == 50:
            return value
        raise RuntimeError("The One Rupee installation identity file is invalid.")
    except OSError as error:
        raise RuntimeError(
            f"Cannot create the One Rupee data directory at {DATA_DIR}. "
            "Check the current user's write permissions."
        ) from error


def is_activated():
    if not ACTIVATION_FILE.exists():
        return False
    try:
        return json.loads(ACTIVATION_FILE.read_text(encoding="utf-8")).get("activated") is True
    except (OSError, json.JSONDecodeError):
        return False


def get_member_id():
    if not ACTIVATION_FILE.exists():
        return None
    try:
        return json.loads(ACTIVATION_FILE.read_text(encoding="utf-8")).get("member_id")
    except (OSError, json.JSONDecodeError):
        return None


def save_activation(member_id):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ACTIVATION_FILE.write_text(
        json.dumps({"activated": True, "member_id": member_id}, indent=4),
        encoding="utf-8",
    )


def clear_activation():
    if ACTIVATION_FILE.exists():
        ACTIVATION_FILE.unlink()
