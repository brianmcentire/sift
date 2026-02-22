"""File classification: extension → (ext_lower, file_category)."""
from __future__ import annotations

_IMAGE_EXTS = frozenset(
    "jpg jpeg png gif bmp tiff tif webp heic heif svg ico raw cr2 nef arw dng".split()
)
_VIDEO_EXTS = frozenset(
    "mp4 mkv avi mov wmv flv webm m4v mpeg mpg ts 3gp rm rmvb vob".split()
)
_AUDIO_EXTS = frozenset(
    "mp3 flac ogg wav aac m4a wma opus aiff ape".split()
)
_DOCUMENT_EXTS = frozenset(
    "pdf doc docx xls xlsx ppt pptx odt ods odp rtf txt md rst tex"
    " csv json yaml yml xml html htm".split()
)
_ARCHIVE_EXTS = frozenset(
    "zip tar gz bz2 xz 7z rar zst lz4 lzma tgz tbz2".split()
)
_CODE_EXTS = frozenset(
    "py js ts jsx tsx go rs c cpp cc h hpp java kt swift rb php lua sh bash zsh"
    " ps1 cs vb sql r m f90 f95 scala clj hs elm".split()
)
_DISK_EXTS = frozenset(
    "vmdk vdi vhd vhdx img iso qcow2 ost pst nbd".split()
)
_FONT_EXTS = frozenset("ttf otf woff woff2 eot".split())
_EXECUTABLE_EXTS = frozenset("exe dll so dylib bin apk deb rpm".split())


def classify_file(filename: str) -> tuple[str, str]:
    """
    Return (ext_lower, file_category).
    ext_lower is the lowercase extension without the leading dot.
    """
    dot_idx = filename.rfind(".")
    if dot_idx <= 0 or dot_idx == len(filename) - 1:
        return "", "other"

    ext = filename[dot_idx + 1:].lower()

    if ext in _IMAGE_EXTS:
        category = "image"
    elif ext in _VIDEO_EXTS:
        category = "video"
    elif ext in _AUDIO_EXTS:
        category = "audio"
    elif ext in _DOCUMENT_EXTS:
        category = "document"
    elif ext in _ARCHIVE_EXTS:
        category = "archive"
    elif ext in _CODE_EXTS:
        category = "code"
    elif ext in _DISK_EXTS:
        category = "disk"
    elif ext in _FONT_EXTS:
        category = "font"
    elif ext in _EXECUTABLE_EXTS:
        category = "executable"
    else:
        category = "other"

    return ext, category
