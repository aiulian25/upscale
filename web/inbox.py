"""The inbox folder: image files dropped into data/inbox become Ready files, as if dropped on the page."""
import os
import shutil
import stat
import threading
import time
import traceback
from functools import partial

import config
from jobs import LOCKED_STATUSES, safe_file_name


def copy_without_links(path, target):
    """Copies a file from the inbox, refusing a link put in its place since it was listed."""
    with open(path, "rb", opener=lambda name, flags: os.open(name, flags | os.O_NOFOLLOW)) as original, \
            target.open("wb") as copy:
        shutil.copyfileobj(original, copy)


class InboxWatcher:
    """Takes in the files dropped into the inbox one at a time, oldest first, once they have stopped growing.

    With autostart each one starts with the shared defaults, and the next is only taken in once it has finished, so
    the files still to run wait in the folder, where they can still be taken back.
    """

    def __init__(self, store, settings_provider, inbox_dir=config.INBOX_DIR, autostart=config.INBOX_AUTOSTART):
        self.store = store
        self.settings_provider = settings_provider
        self.inbox_dir = inbox_dir
        self.rejected_dir = inbox_dir / config.INBOX_REJECTED_NAME
        self.autostart = autostart
        # (modified time, size) of each file at the last scan: the same twice means it has finished copying
        self.signatures = {}
        # Files that couldn't be moved out of the inbox, left alone until they change
        self.stuck = {}
        self.rejected_dir.mkdir(parents=True, exist_ok=True)

    def start(self):
        threading.Thread(target=self._watch_forever, name="inbox", daemon=True).start()

    def _watch_forever(self):
        while True:
            try:
                self.scan_once()
            except Exception:
                traceback.print_exc()
            time.sleep(config.INBOX_POLL_SECONDS)

    def scan_once(self):
        signatures = self._signatures()
        stable = [path for path, signature in signatures.items()
                  if self.signatures.get(path) == signature and self.stuck.get(path) != signature]
        self.signatures = signatures
        if not stable:
            return
        if self.autostart and self._previous_in_line():
            return
        oldest = min(stable, key=lambda path: (signatures[path], path.name))
        self._take(oldest, signatures[oldest])

    def _signatures(self):
        """Each image waiting here: plain files only, not links, folders or hidden files, and not empty ones, which may
        be about to be written."""
        signatures = {}
        for path in self.inbox_dir.iterdir():
            if path.name.startswith(config.HIDDEN_FILE_PREFIX):
                continue
            if path.suffix.lower() not in config.ALLOWED_INPUT_EXTENSIONS:
                continue
            status = path.lstat()
            if stat.S_ISREG(status.st_mode) and status.st_size:
                signatures[path] = (status.st_mtime_ns, status.st_size)
        return signatures

    def _previous_in_line(self):
        return any(job["source"] == config.SOURCE_INBOX and job["status"] in LOCKED_STATUSES
                   for job in self.store.all_jobs())

    def _take(self, path, signature):
        """Adds the file as if uploaded and removes it here; one the app can't read as an image goes to rejected/."""
        # File names on disk may hold any bytes; this one is shown on the page and saved in jobs.json
        name = safe_file_name(path.name)
        try:
            job = self.store.add(name, self.settings_provider(), write_input=partial(copy_without_links, path),
                                 source=config.SOURCE_INBOX)
        except (ValueError, PermissionError) as error:
            print(config.INBOX_REJECTED_LOG.format(name=name, folder=config.INBOX_REJECTED_NAME, error=error),
                  flush=True)
            self._move_out(path, name, signature, partial(path.replace, self._rejected_path(path)))
            return
        # A file that stays here would be taken in again after a restart, so it isn't taken in at all
        if not self._move_out(path, name, signature, path.unlink):
            self.store.delete(job["id"])
            return
        if self.autostart:
            self.store.start([job["id"]], self.settings_provider())

    def _move_out(self, path, name, signature, move):
        """Whether the file left the inbox; one that can't (a read-only folder) is left alone until it changes."""
        try:
            move()
        except OSError as error:
            print(config.INBOX_STUCK_LOG.format(name=name, error=error), flush=True)
            self.stuck[path] = signature
            return False
        return True

    def _rejected_path(self, path):
        """rejected/<name>, with the time added when a file of that name was rejected before, so neither is lost."""
        target = self.rejected_dir / path.name
        if not os.path.lexists(target):
            return target
        return self.rejected_dir / config.INBOX_REJECTED_CLASH_NAME.format(stem=path.stem, stamp=time.time_ns(),
                                                                          suffix=path.suffix)
