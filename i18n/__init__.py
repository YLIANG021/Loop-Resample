"""Locale tables for Loop Resample: English and Simplified Chinese.

The language is whatever Blender is set to -- there is no switch of our own, because the
add-on has exactly one surface (the viewport overlay) and it should read like the rest of
the interface around it.  ``pgettext`` therefore asks Blender which locale it picked, and
falls back to English for anything it cannot match.

The shape of the table is the one yl_meshcheckhud uses: every string is written in English
in the source, and that English sentence is itself the key.  A missing translation is not an
error, it is the English text, so adding a string without translating it degrades to a
language the user can read rather than to a blank chip.
"""

import bpy

from . import en_US, zh_CN


TRANSLATIONS = {
    "en_US": en_US.TRANSLATIONS,
    "zh_CN": zh_CN.TRANSLATIONS,
    "zh_HANS": zh_CN.TRANSLATIONS,
    "zh_hans": zh_CN.TRANSLATIONS,
    "zh": zh_CN.TRANSLATIONS,
}

_FALLBACK = "en_US"


def _locale_candidates():
    """Every name worth trying for the language Blender is currently answering in.

    ``bpy.app.translations.locale`` is what the interface is actually drawing with, and it
    is the only one of the two that is set even when the user left the language on the
    system default.  ``preferences.view.language`` is the explicit choice, which can disagree
    with it.  Both are tried whole and then down to the language prefix, because the codes
    Blender ships are the broad ones -- Simplified Chinese is ``zh_HANS``, not ``zh_CN``, and
    a table keyed to one spelling still has to answer the other.
    """
    candidates = []
    for value in (
        getattr(bpy.app.translations, "locale", "") or "",
        getattr(bpy.context.preferences.view, "language", "") or "",
    ):
        if not value:
            continue
        candidates.append(value)
        if "_" in value:
            candidates.append(value.split("_", 1)[0])
    candidates.append(_FALLBACK)
    return candidates


def pgettext(message):
    """The string for ``message`` in the language Blender is drawing in."""
    seen = set()
    for candidate in _locale_candidates():
        if candidate in seen:
            continue
        seen.add(candidate)
        translations = TRANSLATIONS.get(candidate)
        if translations is None:
            continue
        return translations.get(("*", message), message)
    return message


def register():
    bpy.app.translations.register(__package__, TRANSLATIONS)


def unregister():
    bpy.app.translations.unregister(__package__)
