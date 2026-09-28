"""Extra models dropped into data/models: each file is checked once at start, and the usable ones join the picker."""
import pickle
import re

import config

# Filled by scan() at start: key -> model, shaped like config.MODELS plus its file; file name -> why it was left out
found = {}
skipped = {}


class UnusableModelError(ValueError):
    """A model the app can't run: the message is shown on the file, the reason in Settings."""

    def __init__(self, model, reason):
        super().__init__(config.ERROR_UNUSABLE_MODEL.format(model=model, reason=reason))
        self.reason = reason


def all_models():
    """Every model the picker offers: the built-in ones, then those found in data/models."""
    return {**config.MODELS, **found}


def load_custom_model(model, path):
    """The model in a custom file, checked to be one the app can run; raises UnusableModelError otherwise."""
    # Imported here, so that listing the models doesn't load torch
    from spandrel import ModelLoader, UnsupportedModelError

    if not path.is_file():
        raise UnusableModelError(model, config.MODEL_GONE)
    try:
        descriptor = ModelLoader().load_from_file(path)
    except UnsupportedModelError:
        raise UnusableModelError(model, config.MODEL_UNKNOWN_ARCHITECTURE) from None
    except pickle.UnpicklingError as error:
        raise UnusableModelError(model, config.MODEL_NOT_JUST_WEIGHTS.format(error=error)) from None
    # A damaged file fails in many ways (a truncated archive, a bad header…): none may stop the app from starting
    except Exception as error:
        raise UnusableModelError(model, config.MODEL_UNREADABLE.format(error=error)) from None
    usable = (descriptor.purpose == config.CUSTOM_MODEL_PURPOSE and descriptor.scale in config.CUSTOM_MODEL_SCALES
              and descriptor.input_channels == descriptor.output_channels == config.CUSTOM_MODEL_CHANNELS)
    if not usable:
        raise UnusableModelError(model, config.MODEL_NOT_SUPPORTED.format(
            architecture=descriptor.architecture.name, scale=descriptor.scale, purpose=descriptor.purpose,
            input_channels=descriptor.input_channels, output_channels=descriptor.output_channels))
    return descriptor


def _name_problem(path):
    """Why a file isn't even read, or None."""
    if path.suffix.lower() not in config.CUSTOM_MODEL_EXTENSIONS:
        return config.MODEL_NOT_A_MODEL_FILE
    if not re.fullmatch(config.CUSTOM_MODEL_NAME_PATTERN, path.stem):
        return config.MODEL_BAD_NAME
    if path.stem in config.MODELS:
        return config.MODEL_BUILT_IN_NAME
    return None


def scan(folder=config.CUSTOM_MODELS_DIR):
    """Reads each file in the folder once. Of a .pth and a .safetensors with the same name, the .safetensors is used."""
    found.clear()
    skipped.clear()
    try:
        paths = sorted(path for path in folder.iterdir()
                       if path.is_file() and not path.name.startswith(config.HIDDEN_FILE_PREFIX))
    except OSError as error:
        skipped[folder.name] = config.MODEL_FOLDER_UNREADABLE.format(error=error)
        return
    for path in paths:
        problem = _name_problem(path)
        if problem:
            skipped[path.name] = problem
            continue
        try:
            descriptor = load_custom_model(path.stem, path)
        except UnusableModelError as error:
            skipped[path.name] = error.reason
            continue
        hint = config.CUSTOM_MODEL_HINT.format(file=path.name, architecture=descriptor.architecture.name,
                                               scale=descriptor.scale)
        found[path.stem] = {"label": path.stem, "hint": hint, "urls": [], "file": path}
