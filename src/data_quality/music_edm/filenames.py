"""Expected-filename generation for music files.

``generate_filename`` turns an artist and a title into the file name stem the
``filename_drift`` check expects. The character rules live in
``CHARACTER_REPLACEMENTS`` in ``constants.py``.
"""

from .constants import CHARACTER_REPLACEMENTS


def generate_filename(artist: str, title: str) -> str:
    """Generate the expected file name stem from artist and title."""

    def process_field(field: str) -> str:
        for old_char, new_char in CHARACTER_REPLACEMENTS.items():
            field = field.replace(old_char, new_char)
        # Remove hyphens from within the field
        field = field.replace("-", "")
        return field

    artist = process_field(artist)
    title = process_field(title)

    filename = f"{artist} - {title}"

    # Handle brackets: replace last ( with -, remove all other ( and )
    if "(" in filename:
        last_paren = filename.rfind("(")
        filename = filename[:last_paren] + "-" + filename[last_paren + 1 :]
        filename = filename.replace("(", "").replace(")", "")

    # At most two dashes remain: process_field strips every hyphen (including
    # mapped lookalikes), so only the separator and the last "(" add one.
    return filename.replace(" ", "")
