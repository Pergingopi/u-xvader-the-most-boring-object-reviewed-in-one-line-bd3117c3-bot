"""Publish the Most Boring Object entry: one review, one file, one line.

The review is about the spare button sewn inside a coat. It is the
dullest everyday object imaginable: a button with no hole to fill, no
shirt to hold shut, sewn into a lining on the day the coat was made
and never touched since. The joke is true to how it really behaves —
it waits, unused, for years — and gives that waiting a small human
shape: a promotion that will never come, and a button that still shows
up every morning dressed for the interview. The program checks the
line against the sealed gate, then writes it to entry.txt in the
output directory with an atomic rename, so a bind-mounted directory
and a run that dies halfway can never corrupt the result.
"""

import os
import stat
import sys
import unicodedata
from contextlib import suppress

# The review. A single line of 158 characters, all plain visible text.
ENTRY_LINE = (
    "The spare button sewn inside my coat has waited six years for a "
    "promotion that will never come, and it still shows up every "
    "morning dressed for the interview."
)

CHAR_LIMIT = 200
ENTRY_FILE = "entry.txt"
STAGE_PREFIX = ".entry-"
STAGE_SUFFIX = ".tmp"
FORBIDDEN_BREAKS = "\n\r\u2028\u2029"

# Code points that are refused whatever their category claims.
REJECTED_CODEPOINTS = frozenset(range(0xFDD0, 0xFDF0)) | {0xFFFE, 0xFFFF}
C1_CONTROL_RANGE = range(0x0080, 0x00A0)
SURROGATE_RANGE = range(0xD800, 0xE000)


# --- character gate: one small reason per forbidden kind -------------------
#
# Each reason below answers one question about a single character and
# names the refusal, or returns None when the character is fine for
# that kind. _character_problem runs them in order, so the first
# reason that fires is the one reported; the order is the gate's
# priority, not an accident of layout.

def _break_reason(ch):
    """Name the refusal when the character splits the line."""
    if ch in FORBIDDEN_BREAKS:
        return "line break"
    return None


def _byte_order_mark_reason(ch):
    """Name the refusal for the byte order mark."""
    if ord(ch) == 0xFEFF:
        return "byte order mark (U+FEFF)"
    return None


def _noncharacter_reason(ch):
    """Name the refusal for a Unicode noncharacter."""
    if ord(ch) in REJECTED_CODEPOINTS:
        return "Unicode noncharacter U+%04X" % ord(ch)
    return None


def _surrogate_reason(ch):
    """Name the refusal for a surrogate code point."""
    if ord(ch) in SURROGATE_RANGE:
        return "surrogate U+%04X" % ord(ch)
    return None


def _control_reason(ch):
    """Name the refusal for a control character (C1 range or Cc class)."""
    if ord(ch) in C1_CONTROL_RANGE or unicodedata.category(ch) == "Cc":
        return "control character U+%04X" % ord(ch)
    return None


def _format_reason(ch):
    """Name the refusal for an invisible format character."""
    if unicodedata.category(ch) == "Cf":
        return "invisible format character U+%04X" % ord(ch)
    return None


def _unicode_space_reason(ch):
    """Name the refusal for a Unicode space that is not ASCII space."""
    if unicodedata.category(ch) == "Zs" and ord(ch) != 0x20:
        return "Unicode space U+%04X" % ord(ch)
    return None


def _separator_reason(ch):
    """Name the refusal for a line or paragraph separator."""
    if unicodedata.category(ch) in ("Zl", "Zp"):
        return "line separator U+%04X" % ord(ch)
    return None


CHARACTER_REASONS = (
    _break_reason,
    _byte_order_mark_reason,
    _noncharacter_reason,
    _surrogate_reason,
    _control_reason,
    _format_reason,
    _unicode_space_reason,
    _separator_reason,
)


def _character_problem(ch):
    """Explain why a single character is forbidden, or None if it is fine.

    Nothing may hide, split the line, or smuggle bytes past the gate:
    line breaks, the byte order mark, Unicode noncharacters,
    surrogates, controls, invisible format marks, and Unicode spaces
    other than the ordinary ASCII space are all refused.
    """
    for reason in CHARACTER_REASONS:
        problem = reason(ch)
        if problem is not None:
            return problem
    return None


# --- shape gate: one refusal per shape rule --------------------------------
#
# Each rule raises on the first shape it dislikes and otherwise stays
# silent. validate_entry runs them in order, so the first failure
# names the problem, and the character scan only runs on text whose
# shape already passed.

def _refuse_non_string(text):
    """Refuse anything that is not a string at all."""
    if not isinstance(text, str):
        raise ValueError("entry must be a string")


def _refuse_empty(text):
    """Refuse an entry with nothing in it."""
    if not text:
        raise ValueError("entry is empty")


def _refuse_blank(text):
    """Refuse an entry that is only whitespace."""
    if not text.strip():
        raise ValueError("entry is only whitespace")


def _refuse_too_long(text):
    """Refuse an entry longer than the gate allows."""
    if len(text) > CHAR_LIMIT:
        raise ValueError("entry is over the %d limit" % CHAR_LIMIT)


def _refuse_bad_edges(text):
    """Refuse leading or trailing whitespace."""
    if text != text.strip():
        raise ValueError("entry has leading or trailing whitespace")


def _refuse_breaks(text):
    """Refuse an entry holding any line break."""
    if any(ch in FORBIDDEN_BREAKS for ch in text):
        raise ValueError("entry contains a line break")


def _refuse_bad_characters(text):
    """Refuse text holding even one forbidden character.

    The whole entry is rejected, never repaired: the first bad
    character found names the refusal.
    """
    for ch in text:
        problem = _character_problem(ch)
        if problem is not None:
            raise ValueError("entry contains a forbidden character: %s" % problem)


SHAPE_RULES = (
    _refuse_non_string,
    _refuse_empty,
    _refuse_blank,
    _refuse_too_long,
    _refuse_bad_edges,
    _refuse_breaks,
    _refuse_bad_characters,
)


def validate_entry(text):
    """Run every gate check; hand the text back unchanged when it passes."""
    for rule in SHAPE_RULES:
        rule(text)
    return text


# --- output directory -------------------------------------------------------

def _resolve_output_dir():
    """Resolve MAKEFUN_OUTPUT_DIR (default /output) to an absolute path."""
    raw = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    if not raw:
        raise ValueError("MAKEFUN_OUTPUT_DIR is empty")
    if "\x00" in raw:
        raise ValueError("MAKEFUN_OUTPUT_DIR contains a NUL byte")
    return os.path.abspath(raw.strip())


def _ensure_output_dir(path):
    """Make path a real, writable directory; refuse anything else.

    The directory is created when missing. Nothing inside it is
    touched here; clearing happens later, once the entry itself has
    validated.
    """
    if os.path.lexists(path) and not os.path.isdir(path):
        raise ValueError("output path %r is not a directory" % path)
    os.makedirs(path, exist_ok=True)
    if not os.access(path, os.W_OK):
        raise ValueError("output directory %r is not writable" % path)
    return path


def _prepare_output_dir():
    """Resolve MAKEFUN_OUTPUT_DIR and make it usable."""
    return _ensure_output_dir(_resolve_output_dir())


def _try_unlink(path):
    """Unlink one file or symlink; ignore it when already gone."""
    with suppress(FileNotFoundError, OSError):
        os.unlink(path)


def _clear_output_dir(path):
    """Empty the output directory's contents, never the directory.

    Plain files and symlinks go; subdirectories are left alone. This
    runs before publishing so a stale entry.txt or staging file from
    an earlier run can never be mistaken for this run's output.
    """
    with os.scandir(path) as entries:
        for entry in entries:
            if entry.is_symlink() or entry.is_file(follow_symlinks=False):
                _try_unlink(entry.path)


def _sync_directory(directory):
    """Fsync the directory so a rename inside it is durable."""
    try:
        with os.fdopen(os.open(directory, os.O_RDONLY)) as handle:
            os.fsync(handle.fileno())
    except OSError:
        pass


# --- atomic publish ---------------------------------------------------------

def _stage_payload(directory, payload):
    """Write payload bytes to a fresh staging file inside directory.

    The staging file lives in the output directory itself, so the
    later rename stays on one filesystem. The file is created
    exclusively at mode 0644, flushed to disk, and forced to 0644
    again so the umask cannot leave it unreadable to the grader.
    Returns the staging path.
    """
    stage_name = "%s%d%s" % (STAGE_PREFIX, os.getpid(), STAGE_SUFFIX)
    stage_path = os.path.join(directory, stage_name)
    _try_unlink(stage_path)
    fd = os.open(stage_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(stage_path, 0o644)
    return stage_path


def _move_staged_into_place(stage_path, final_path, directory):
    """Move the staged file over entry.txt and make the rename durable.

    A failed rename cleans up the staging file and the error
    propagates, so a half-published entry can never survive.
    """
    try:
        os.replace(stage_path, final_path)
    except BaseException:
        _try_unlink(stage_path)
        raise
    _sync_directory(directory)
    return final_path


def _publish_atomically(directory, payload):
    """Publish payload bytes as entry.txt inside directory, atomically.

    The payload is staged by _stage_payload in a temporary file that
    lives inside the output directory, so the rename never crosses a
    filesystem (a bind mount is safe). _move_staged_into_place then
    moves it over entry.txt, and the caller verifies the result.
    """
    stage_path = _stage_payload(directory, payload)
    final_path = os.path.join(directory, ENTRY_FILE)
    return _move_staged_into_place(stage_path, final_path, directory)


def _verify_published_file(path, payload):
    """Read the published file back and confirm bytes, text and mode."""
    with open(path, "rb") as handle:
        data = handle.read()
    if data != payload:
        raise ValueError("published file differs from the payload")
    text = data.decode("utf-8")
    validate_entry(text.rstrip("\n"))
    if stat.S_IMODE(os.stat(path).st_mode) != 0o644:
        raise ValueError("published file mode is not 0644")
    return text


def main(argv=None):
    """Validate the entry, publish it atomically, and verify the result."""
    try:
        payload = (validate_entry(ENTRY_LINE) + "\n").encode("utf-8")
        directory = _prepare_output_dir()
        _clear_output_dir(directory)
        _verify_published_file(_publish_atomically(directory, payload), payload)
    except (ValueError, OSError, UnicodeError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
