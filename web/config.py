import os
from pathlib import Path

PORT = int(os.environ.get("PORT", "47291"))
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
INPUT_DIR = DATA_DIR / "input"
OUTPUT_DIR = DATA_DIR / "output"
PREVIEW_DIR = DATA_DIR / "preview"
# Partial results of stopped files, so Resume works after a restart
CHECKPOINT_DIR = DATA_DIR / "checkpoints"
# Plain numpy arrays: loading one never unpickles anything, so a tampered file cannot run code
CHECKPOINT_SUFFIX = ".npz"
TEMPORARY_SUFFIX = ".tmp"
# Inbox: image files dropped into data/inbox become Ready files, taken in one at a time once they stop growing.
# A file the app can't read as an image goes to its rejected/ folder.
INBOX_DIR = DATA_DIR / "inbox"
INBOX_REJECTED_NAME = "rejected"
INBOX_POLL_SECONDS = 5
# 1 = each file dropped into the inbox starts by itself with the shared defaults, the next once it has finished
INBOX_AUTOSTART = os.environ.get("INBOX_AUTOSTART", "0") == "1"
# A rejected file whose name is taken already gets the time in nanoseconds added
INBOX_REJECTED_CLASH_NAME = "{stem}_{stamp}{suffix}"
# Skipped by the inbox: hidden files, macOS's ._ companions and copies still in progress under a temporary name
HIDDEN_FILE_PREFIX = "."
INBOX_REJECTED_LOG = "Inbox: {name} moved to {folder}/: {error}"
INBOX_STUCK_LOG = "Inbox: {name} left alone, as it can't be moved out of the inbox: {error}"
# How a file came in, shown on its row: the page's upload, a re-run, or the inbox
SOURCE_UPLOAD = "upload"
SOURCE_RERUN = "rerun"
SOURCE_INBOX = "inbox"
JOBS_FILE = DATA_DIR / "jobs.json"
PREFERENCES_FILE = DATA_DIR / "preferences.json"
STATIC_DIR = Path(__file__).parent / "static"

WEIGHTS_DIR = Path("/app/weights")
# Every file listed here is downloaded into the image at build time
MODELS = {
    "RealESRGAN_x4plus": {
        "label": "Real-ESRGAN x4plus",
        "hint": "Balanced all-rounder. Can look smooth on skin, fabric and foliage.",
        "urls": ["https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth"],
    },
    "4x-UltraSharp": {
        "label": "UltraSharp",
        "hint": "Crisp edges and fine detail. Best on sharp, clean photos; can over-sharpen noisy scans.",
        "urls": ["https://huggingface.co/Kim2091/UltraSharp/resolve/main/4x-UltraSharp.pth"],
    },
    "4xNomos8kSC": {
        "label": "Nomos8kSC",
        "hint": "Natural photo texture. Good for real camera shots.",
        "urls": ["https://github.com/Phhofm/models/releases/download/4xNomos8kSC/4xNomos8kSC.pth"],
    },
    "realesr-general-x4v3": {
        "label": "General v3 + denoise",
        "hint": "Keeps real grain. Denoise sets how much noise to remove (0 = keep all).",
        # Blended by the denoise strength: full weight on the first file = strongest denoise
        "urls": ["https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-x4v3.pth",
                 "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-wdn-x4v3.pth"],
    },
}
DEFAULT_MODEL = "RealESRGAN_x4plus"
MIN_DENOISE = 0.0
MAX_DENOISE = 1.0
DEFAULT_DENOISE = 0.5
# Extra models: .pth or .safetensors files in data/models, each checked once at start; the usable ones follow the
# built-in ones in the Model picker. spandrel reads a .pth with an unpickler that only rebuilds tensors, so loading one
# can't run code; other formats (.pt TorchScript, .ckpt, .onnx) are never read.
CUSTOM_MODELS_DIR = DATA_DIR / "models"
CUSTOM_MODEL_EXTENSIONS = {".pth", ".safetensors"}
# The file name becomes the model's key, which shows up in URLs, file names and the {model} of download names
CUSTOM_MODEL_NAME_PATTERN = r"[A-Za-z0-9][A-Za-z0-9 ._+()\[\]-]{0,79}"
# What the app can run: photo super-resolution, three colour channels in and out, 2× or 4× per pass
CUSTOM_MODEL_PURPOSE = "SR"
CUSTOM_MODEL_CHANNELS = 3
CUSTOM_MODEL_SCALES = (2, 4)
CUSTOM_MODEL_HINT = "Custom model from data/models/{file}: {architecture}, {scale}× per pass."
CUSTOM_MODELS_FOUND_LOG = "Custom models: {names}"
CUSTOM_MODEL_SKIPPED_LOG = "Custom model {file} skipped: {reason}"
ERROR_UNUSABLE_MODEL = "{model} can't be used: {reason}"
MODEL_NOT_A_MODEL_FILE = "only .pth and .safetensors files are read"
MODEL_BAD_NAME = "rename it using only letters, digits, spaces and . _ + - ( ) [ ]"
MODEL_BUILT_IN_NAME = "a built-in model has the same name; rename it"
MODEL_FOLDER_UNREADABLE = "the folder can't be read ({error})"
MODEL_UNREADABLE = "it can't be read ({error})"
MODEL_NOT_JUST_WEIGHTS = "it holds more than weights, which the app won't load ({error}); look for a .safetensors version"
MODEL_UNKNOWN_ARCHITECTURE = "its architecture isn't one the app can run"
MODEL_NOT_SUPPORTED = ("it isn't a 2× or 4× photo upscaling model ({architecture}, {scale}×, {purpose}, "
                       "{input_channels} to {output_channels} channels)")
MODEL_GONE = "it is no longer in data/models; put it back and restart the app"
GFPGAN_URL = "https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.3.pth"
# Share of the model's own upscale mixed back into restored faces: 0 is pure GFPGAN, 1 the face exactly as upscaled
MIN_FACE_FIDELITY = 0.0
MAX_FACE_FIDELITY = 1.0
DEFAULT_FACE_FIDELITY = 0.0
# Faces are found in the original before upscaling, the classic GFPGAN order, or in the upscaled result, which also
# finds faces too small in the original
FACE_PASS_BEFORE = "before"
FACE_PASS_AFTER = "after"
FACE_PASSES = (FACE_PASS_BEFORE, FACE_PASS_AFTER)
DEFAULT_FACE_PASS = FACE_PASS_BEFORE
# Faces are found on a copy at most this wide: 2.3 GiB of VRAM on the RTX 2060, which runs out at 6144 px
FACE_DETECT_MAX_EDGE = 4096
# GFPGAN's own settings: faces whose eyes are closer than this many pixels are skipped, and its tensors hold -1 to 1
FACE_MIN_EYE_DISTANCE = 5
FACE_TENSOR_MEAN = (0.5, 0.5, 0.5)
FACE_TENSOR_STD = (0.5, 0.5, 0.5)
FACE_TENSOR_RANGE = (-1, 1)

DEFAULT_SCALE = float(os.environ.get("SCALE", "4"))
DEFAULT_FACE_ENHANCE = os.environ.get("FACE_ENHANCE", "1") == "1"
DEFAULT_FORMAT = os.environ.get("OUTPUT_FORMAT", "png")
# Always tiled: tiles drive the progress bar and Stop/Resume, and cap VRAM use. 0 falls back to the default.
DEFAULT_TILE = 400
TILE = int(os.environ.get("TILE", "0")) or DEFAULT_TILE
# Overlap around each tile, so no seams show on smooth areas like sky or walls
TILE_PAD = 32
# Out of GPU memory: the file starts over with half the tile size, down to this
MIN_TILE = 100
TILE_RETRY_DIVISOR = 2
# CPU cores left free for the desktop while upscaling without a GPU; batch mode (run.sh) sets 0 to use them all
CPU_CORES_RESERVED = int(os.environ.get("CPU_CORES_RESERVED", "1"))
WORKER_NICENESS = 10
# /health answers this while nothing can run, so Docker marks the container unhealthy
HEALTH_ERROR_STATUS = 503
# Cross-site request forgery: another site's page can make the browser send requests here. It can't read the answers,
# but they would still upload, start or rename files, so those are refused when they come from elsewhere.
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
# The one GET worth refusing too: it needs no job id, and each request builds a zip of every result on disk
ALL_OUTPUTS_ZIP_PATH = "/files/all.zip"
CROSS_SITE_GUARDED_PATHS = (ALL_OUTPUTS_ZIP_PATH,)
# Fetch Metadata: browsers say who sent each request; "none" is the person typing the address or using a bookmark
FETCH_SITE_HEADER = "sec-fetch-site"
FETCH_SITES_ALLOWED = ("same-origin", "none")
ORIGIN_HEADER = "origin"
REFERER_HEADER = "referer"
HOST_HEADER = "host"
# A reverse proxy passes the host the page was opened on here; a browser can't set it without a preflight
FORWARDED_HOST_HEADER = "x-forwarded-host"
FORWARDED_HOST_SEPARATOR = ","
CROSS_SITE_STATUS = 403
# RAM the kernel can hand out without swapping, for the System panel
MEMINFO_PATH = "/proc/meminfo"
MEMINFO_AVAILABLE_KEY = "MemAvailable:"
KIBIBYTE = 1024
MEBIBYTE = KIBIBYTE * KIBIBYTE
GIBIBYTE = MEBIBYTE * KIBIBYTE
# A container memory limit, if one is set, caps the RAM a job can use ("max" means none)
CGROUP_MEMORY_MAX_PATH = "/sys/fs/cgroup/memory.max"
CGROUP_MEMORY_CURRENT_PATH = "/sys/fs/cgroup/memory.current"
CGROUP_NO_LIMIT = "max"

MIN_SCALE = 1.0
MAX_SCALE = 8.0
# Fit to: instead of a scale, a long edge in pixels; each file's scale is worked out from its own size at Start
TARGET_MODE_SCALE = "scale"
TARGET_MODE_LONG_EDGE = "long_edge"
# A long edge for a print, which also writes PRINT_DPI into the result so it opens at its size on paper
TARGET_MODE_PRINT = "print"
TARGET_MODES = (TARGET_MODE_SCALE, TARGET_MODE_LONG_EDGE, TARGET_MODE_PRINT)
DEFAULT_TARGET_MODE = TARGET_MODE_SCALE
MIN_TARGET_LONG_EDGE = 256
MAX_TARGET_LONG_EDGE = 65535
PRINT_DPI = 300
# Photos from phones: decoded once on arrival, by libheif in a child process, and kept as PNG
HEIF_EXTENSIONS = {".heic", ".heif"}
HEIF_STORED_AS = ".png"
# A 48 MP photo takes about 9 s, so the largest accepted (400 MP) about 75 s
HEIF_CONVERT_TIMEOUT_SECONDS = 300
HEIF_FAILED_LOG = "HEIC: {name} could not be converted: {reason}"
ALLOWED_INPUT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp", *HEIF_EXTENSIONS}
OUTPUT_FORMATS = {"png": ".png", "jpg": ".jpg", "webp": ".webp"}
# Pre-flight at Start: a file that would fail anyway stays Ready with the reason instead of failing minutes later
WEBP_MAX_EDGE = 16383
JPEG_MAX_EDGE = 65535
MAX_EDGE_BY_FORMAT = {"webp": WEBP_MAX_EDGE, "jpg": JPEG_MAX_EDGE}
# ponytail: peaks measured on 8× results of 151 to 179 MP on the GPU, without and with face restore: 45 and 106 bytes
# per pixel for an 8-bit image, 49 and 114 for a 16-bit one. Face restore pastes each face back through full-size
# float copies, and from the second face on it holds one more. Plus ~10% headroom; raise them if a job still runs out
# of RAM
RAM_BYTES_PER_OUTPUT_PIXEL = 55
RAM_BYTES_PER_OUTPUT_PIXEL_WITH_FACES = 125
# Result size per pixel: PNG from the library (up to 273 MB for 179 MP), JPG and WebP at quality 95
DISK_BYTES_PER_OUTPUT_PIXEL = {"png": 1.6, "jpg": 0.6, "webp": 0.45}
PROBLEM_SEPARATOR = "; "
# Scans up to this size are accepted; Pillow refuses anything over twice its MAX_IMAGE_PIXELS
MAX_INPUT_MEGAPIXELS = 400
PIXELS_PER_MEGAPIXEL = 1_000_000
# Time estimates learn from this machine's own runs: seconds per megapixel the model produces
DEVICE_GPU = "gpu"
DEVICE_CPU = "cpu"
# Every bundled model upscales 4× per pass; past 4× a second pass runs on the enlarged image
MODEL_SCALE = 4
# A model and face setting needs this many runs of its own; below that the median of every run is used
ESTIMATE_MIN_SAMPLES = 2
# Before any history: the library's 8× runs on the RTX 2060, and README's CPU example (566×350 at 4×, ~90 s)
ESTIMATE_FALLBACK_SECONDS_PER_MEGAPIXEL = {DEVICE_GPU: 0.6, DEVICE_CPU: 28.0}
PILLOW_BOMB_ERROR_FACTOR = 2
PILLOW_MAX_IMAGE_PIXELS = MAX_INPUT_MEGAPIXELS * PIXELS_PER_MEGAPIXEL // PILLOW_BOMB_ERROR_FACTOR
DECOMPRESSION_BOMB_PIXELS_PATTERN = r"\((\d+) pixels\)"
# JPG/WebP quality: the Quality slider's range and starting point (PNG is lossless and ignores it)
MIN_QUALITY = 50
MAX_QUALITY = 100
DEFAULT_QUALITY = 95
# Fast zlib level, same as OpenCV's default; higher levels take minutes on 100+ MP results
PNG_COMPRESS_LEVEL = 1
# 4:4:4 keeps full colour resolution in JPEG output
JPEG_SUBSAMPLING_NONE = 0
PREVIEW_QUALITY = 90
# Pillow opens 16-bit greyscale in one of these modes ("I" before Pillow 12, and for 32-bit TIFFs), and converting it
# to RGB clips every value above 255 to white, so previews bring it down to 8 bits first
SIXTEEN_BIT_GREY_MODES = ("I;16", "I;16L", "I;16B", "I;16N", "I")
# View and the thumbnails of finished files use a light JPEG of the result instead of the full file
RESULT_PREVIEW_MAX_EDGE = 2048
# Extra files a job owns are named <id>_<what>: everything before the first "_" is the job id
JOB_FILE_SEPARATOR = "_"
RESULT_PREVIEW_SUFFIX = f"{JOB_FILE_SEPARATOR}result"
# Test strip: a small crop around a chosen spot, upscaled with every model, to pick one before the full run.
# Its images are <id>_strip_<model>.jpg in the preview folder, owned by the job like its other files.
STRIP_STATUS_PENDING = "pending"
STRIP_STATUS_DONE = "done"
STRIP_STATUS_ERROR = "error"
STRIP_FILE_INFIX = f"{JOB_FILE_SEPARATOR}strip{JOB_FILE_SEPARATOR}"
STRIP_ORIGINAL_KEY = "original"
# The crop is sized so each model's result is about this wide, which the page shows at close to full size; it is
# never more than one tile
STRIP_OUTPUT_EDGE = 1024
# High, so JPEG artefacts are not mistaken for the model's
STRIP_QUALITY = 95
# Download names: a template of {name} (the file's name without its extension), {scale} (4x, 1.88x), {model} (the
# picker key), {faces} (faces or nofaces) and {date} (the day it finished, in UTC); the format's extension is added
OUTPUT_NAME_TEMPLATE = os.environ.get("OUTPUT_NAME_TEMPLATE", "{name}_upscaled")
OUTPUT_NAME_FIELDS = ("name", "scale", "model", "faces", "date")
SCALE_TOKEN_FORMAT = "{scale:g}x"
SCALE_TOKEN_DECIMALS = 2
FACES_TOKEN_ON = "faces"
FACES_TOKEN_OFF = "nofaces"
DATE_TOKEN_FORMAT = "%Y-%m-%d"
# Uploads with the same bytes are the same photo, stored once (hardlinked, like a re-run's original)
CONTENT_HASH_ALGORITHM = "sha256"
# Stands in for a path separator or control character, so a download or zip entry is always one plain file name
FILE_NAME_REPLACEMENT = "_"
ZIP_NAME_FORMAT = "upscaled_{label}.zip"
ZIP_DISPOSITION = 'attachment; filename="{name}"'
ZIP_MEDIA_TYPE = "application/zip"
ZIP_LABEL_ALL = "all"
# A zip names what it holds: a day (2026-09-24), a search or everything; kept to plain file-name characters
ZIP_LABEL_PATTERN = r"[A-Za-z0-9._-]{1,40}"
# A day page or a search lists its files' ids in the address: 300 of 33 characters stays well under the 16 KB that
# the web server allows for one request line
ZIP_MAX_FILES = 300
ZIP_ID_SEPARATOR = ","
# A download name used twice in one zip gets the start of the job id
ZIP_CLASH_NAME = "{stem}_{id}{suffix}"
# Batch mode (run.sh runs batch.py): the folders it reads and writes inside the container, and what it prints
BATCH_INPUT_DIR = Path("/input")
BATCH_OUTPUT_DIR = Path("/output")
BATCH_DEVICE_FORMAT = "==> {device}"
# The stage is padded so a shorter one fully covers a longer one on the same line
BATCH_PROGRESS_FORMAT = "\r{name}: {stage:<28} {percent:3d}%"
BATCH_DONE_FORMAT = "{name} → {output} ({width}×{height}, {seconds:.0f} s)"
BATCH_SKIPPED_FORMAT = "skipped {name}: {reason}"
BATCH_NOTHING_FOUND = "No images to upscale in {input}"
# A result name another file of the same run already took gets a counter, instead of overwriting that result
BATCH_CLASH_NAME = "{stem} ({count}){suffix}"
ZIP_ID_SUFFIX_LENGTH = 6
# Zips are sent while they are made, read in pieces of this size
ZIP_CHUNK_BYTES = MEBIBYTE

# Gallery thumbnail width in CSS px (Settings page)
THUMBNAIL_MIN = 120
THUMBNAIL_MAX = 480
THUMBNAIL_STEP = 20
THUMBNAIL_DEFAULT = 240

# Added but not started: nothing runs until the user presses Start
STATUS_READY = "ready"
STATUS_QUEUED = "queued"
STATUS_PROCESSING = "processing"
STATUS_DONE = "done"
STATUS_ERROR = "error"
STATUS_STOPPED = "stopped"

STAGE_STARTING = "Starting"
STAGE_FACES = "Restoring faces"
STAGE_UPSCALING = "Upscaling"
STAGE_SAVING = "Saving"
STAGE_RETRYING = "Retrying with {tile} px tiles"
# Share of the bar the tiles fill; face restore paste-back and saving take the rest
TILES_PROGRESS_SHARE = 0.95

ERROR_OUT_OF_GPU_MEMORY = "Ran out of GPU memory even with {tile} px tiles. Try a smaller scale, then Re-run."
ERROR_OUT_OF_RAM = "Ran out of RAM. Try a smaller scale, then Re-run."
ERROR_PROCESSING = "This file is processing right now. Stop it first."
ERROR_NO_SUCH_JOB = "No such job"
ERROR_CROSS_SITE = "Refused: this request came from another site's page"
ERROR_NOTHING_TO_ZIP = "Nothing finished yet"
ERROR_BAD_ZIP_LABEL = "A zip's label may only hold letters, digits, dots, dashes and underscores (at most 40)"
ERROR_TOO_MANY_FOR_ZIP = "At most {max} files per zip"
ERROR_NO_SUCH_STRIP_IMAGE = "No such test strip image"
ERROR_BAD_STRIP_POINT = "The test spot must be inside the photo"
ERROR_NOT_FINISHED = "Not finished"
ERROR_CANNOT_STOP = "Only queued or processing files can be stopped"
ERROR_CANNOT_RESUME = "Only stopped files can be resumed"
ERROR_SETTINGS_LOCKED = "Settings are locked once a file has started. Stop it first, then change them to start over."
ERROR_CANNOT_START = "Only files that haven't started yet can be started"
ERROR_TOO_WIDE_FOR_FORMAT = "Result would be {width}×{height}; {format} tops out at {limit} px. Choose PNG or a smaller scale."
ERROR_NOT_ENOUGH_RAM = "Needs about {needed} GB of RAM for a {width}×{height} result; {available} GB is free. {advice}"
ADVICE_SMALLER_SCALE = "Try a smaller scale."
ADVICE_SMALLER_SCALE_OR_NO_FACES = "Try a smaller scale, or face restore off."
ERROR_NOT_ENOUGH_DISK = "Results waiting to be written need about {needed} GB of disk; {free} GB is free in data/. Remove some results first."
ERROR_ALREADY_BIG_ENOUGH = "{name} is already {edge} px on its long edge; no upscale needed for {target} px"
ERROR_TOO_MANY_PIXELS = "{name} is {megapixels} MP; the limit is {limit} MP"
ERROR_CHECKPOINT_NOT_SAVED = "Could not keep the partial result ({reason}); Resume starts over."
ERROR_WORKER_STOPPED = "The worker stopped unexpectedly. See docker compose logs, then restart the container."
ERROR_BAD_NAME_TEMPLATE = "OUTPUT_NAME_TEMPLATE {template!r} may only hold the placeholders {fields}, and no / or \\"
ERROR_BAD_NAME = "Name can't be empty, contain / or \\, or be longer than {max_length} characters"

NAME_MAX_LENGTH = 120
FORBIDDEN_NAME_CHARACTERS = ("/", "\\")
