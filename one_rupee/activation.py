"""Installation identity and optional local activation helpers."""

import hashlib
import json
import uuid
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path.home() / ".one_rupee"
ACTIVATION_FILE = DATA_DIR / ".one_rupee_activation.json"
INSTALLATION_MARKER = PACKAGE_DIR / ".installation_id"


def get_installation_id():
    """Return a stable id for this installed package copy.

    The marker is included in the installed distribution, so a normal
    uninstall removes it; reinstalling creates a fresh marker and therefore a
    fresh installation id. Persistent payment data remains in ~/.one_rupee.
    """
    try:
        value = INSTALLATION_MARKER.read_text(encoding="utf-8").strip()
    except OSError:
        value = ""

    if value.startswith("one_rupee_install_") and len(value) == 50:
        return value

    installation_id = "one_rupee_install_" + uuid.uuid4().hex
    try:
        INSTALLATION_MARKER.write_text(installation_id + "\n", encoding="utf-8")
        return installation_id
    except OSError:
        marker = PACKAGE_DIR / "__init__.py"
        stat = marker.stat()
        seed = f"{marker.resolve()}:{stat.st_mtime_ns}:{stat.st_size}"
        return "one_rupee_install_" + hashlib.sha256(seed.encode()).hexdigest()[:32]


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
