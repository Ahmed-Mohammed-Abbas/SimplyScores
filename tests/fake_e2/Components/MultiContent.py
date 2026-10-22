def MultiContentEntryText(**kw):
    for key in ("pos", "size", "font", "flags", "text"):
        assert key in kw, key
    assert isinstance(kw["text"], str)
    return ("text", kw)


def MultiContentEntryPixmapAlphaBlend(**kw):
    assert kw.get("png") is not None
    return ("pix", kw)
