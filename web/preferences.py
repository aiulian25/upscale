"""App-wide preferences shared by every browser that opens the app: thumbnail size and the default settings."""
import json
import threading

import config
from jobs import validate_settings

# Checked once at start-up: a bad SCALE or OUTPUT_FORMAT in the compose file stops the app with a clear message
ENV_DEFAULTS = validate_settings(config.DEFAULT_SCALE, config.DEFAULT_FACE_ENHANCE, config.DEFAULT_FORMAT,
                                 config.DEFAULT_MODEL, config.DEFAULT_DENOISE)
TARGET_FIELDS = ("target_mode", "target_long_edge")
ERROR_INCOMPLETE_DEFAULTS = "Defaults need scale, face_enhance and output_format together"
# One read-modify-write at a time, so saving the thumbnail size and the defaults at once loses neither
_save_lock = threading.Lock()


def limits():
    return {"min": config.THUMBNAIL_MIN, "max": config.THUMBNAIL_MAX, "step": config.THUMBNAIL_STEP,
            "default": config.THUMBNAIL_DEFAULT}


def _valid_thumbnail_size(size):
    return isinstance(size, int) and config.THUMBNAIL_MIN <= size <= config.THUMBNAIL_MAX


def _validated(settings):
    return validate_settings(settings["scale"], settings["face_enhance"], settings["format"], settings["model"],
                             settings["denoise"], settings["quality"], settings["face_fidelity"], settings["face_pass"],
                             settings["target_mode"], settings["target_long_edge"])


def _read_saved():
    """What was saved, or nothing if the file is missing or unreadable: it only holds preferences."""
    try:
        saved = json.loads(config.PREFERENCES_FILE.read_text())
    except (OSError, ValueError):
        return {}
    return saved if isinstance(saved, dict) else {}


def _shared_defaults(saved_defaults):
    """The env defaults, overridden by each saved field that still validates on its own.

    A model that has left the picker since, or a hand-edited value, falls back alone instead of breaking the page.
    Fit to's mode and long edge only validate together, so they are restored together.
    """
    fields = [{key: value} for key, value in saved_defaults.items() if key not in TARGET_FIELDS]
    fields.append({key: saved_defaults[key] for key in TARGET_FIELDS if key in saved_defaults})
    defaults = dict(ENV_DEFAULTS)
    for field in fields:
        try:
            defaults = _validated({**defaults, **field})
        except (TypeError, ValueError):
            pass
    return defaults


def load():
    saved = _read_saved()
    thumbnail_size = saved.get("thumbnail_size")
    saved_defaults = saved.get("defaults")
    return {"thumbnail_size": thumbnail_size if _valid_thumbnail_size(thumbnail_size) else config.THUMBNAIL_DEFAULT,
            "limits": limits(),
            "defaults": _shared_defaults(saved_defaults if isinstance(saved_defaults, dict) else {})}


def save(thumbnail_size=None, defaults=None):
    """Saves what is given and keeps the rest of the file; the defaults only ever as a complete, valid set."""
    if thumbnail_size is not None and not _valid_thumbnail_size(thumbnail_size):
        raise ValueError(f"Thumbnail size must be between {config.THUMBNAIL_MIN} and {config.THUMBNAIL_MAX} px")
    changes = {"thumbnail_size": thumbnail_size, "defaults": None if defaults is None else _validated(defaults)}
    changes = {key: value for key, value in changes.items() if value is not None}
    if not changes:
        return load()
    with _save_lock:
        saved = {**_read_saved(), **changes}
        temporary = config.PREFERENCES_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(saved))
        temporary.replace(config.PREFERENCES_FILE)
    return load()
