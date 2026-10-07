CATEGORIES = {
    "mr_freshers": "Mr Freshers",
    "mrs_freshers": "Mrs Freshers",
    "mr_stylist": "Mr Stylist",
    "mrs_stylist": "Mrs Stylist",
}
MAX_PER_CATEGORY = 3
MAX_UPLOAD_BYTES = 3 * 1024 * 1024

# mimetype -> (magic bytes, file extension)
SIGNATURES = {
    "image/jpeg": (b"\xff\xd8\xff", "jpg"),
    "image/png": (b"\x89PNG\r\n\x1a\n", "png"),
    "image/webp": (b"RIFF", "webp"),
}


def validate_image(file):
    """Return an error message, or None if the upload is a small, real image."""
    if file.mimetype not in SIGNATURES:
        return "Please upload a JPG, PNG or WEBP image."
    signature = SIGNATURES[file.mimetype][0]
    head = file.stream.read(12)
    file.stream.seek(0)
    if not head.startswith(signature) or (file.mimetype == "image/webp" and head[8:12] != b"WEBP"):
        return "That file does not look like a valid image."
    file.stream.seek(0, 2)
    size = file.stream.tell()
    file.stream.seek(0)
    if size > MAX_UPLOAD_BYTES:
        return "Image must be under 3 MB."
    return None
