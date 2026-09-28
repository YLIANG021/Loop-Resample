"""Locale tables for Loop Resample: English plus twelve translations of it.

The language is whatever Blender is set to -- there is no switch of our own, because the
add-on has exactly one surface (the viewport overlay) and it should read like the rest of
the interface around it.  ``pgettext`` therefore asks Blender which locale it picked, and
falls back to English for anything it cannot match.

The shape of the table is the one yl_meshcheckhud uses: every string is written in English
in the source, and that English sentence is itself the key.  A missing translation is not an
error, it is the English text, so adding a string without translating it degrades to a
language the user can read rather than to a blank chip.  ``en_US.MESSAGES`` is the list every
other file is written against, and each locale answers all of it: forty-seven strings in,
forty-seven out.
"""

import bpy

from . import (
    de_DE,
    en_US,
    es_ES,
    fr_FR,
    it_IT,
    ja_JP,
    ko_KR,
    pl_PL,
    pt_PT,
    ru_RU,
    vi_VN,
    zh_CN,
    zh_TW,
)

# Each table and every spelling of its language worth answering.  The first code of each group
# is the one Blender 5.2 actually reports (``bpy.app.translations.locales``); the rest are the
# spellings that arrive from elsewhere.  A bare language prefix has to be in there because that
# is what a system locale like ``de_DE.UTF-8`` leaves behind once ``_locale_candidates`` trims
# it, and because Spanish is ``es`` with no country at all while the table's own name is the
# country form.  Note what is *not* aliased: Traditional Chinese gets ``zh_HANT`` and ``zh_TW``
# but never the bare ``zh``, which stays Simplified's, because that is the spelling a Chinese
# system locale collapses to and Simplified is what most of them mean.
_LOCALES = (
    (en_US, ("en_US", "en")),
    (zh_CN, ("zh_HANS", "zh_CN", "zh_hans", "zh")),
    (zh_TW, ("zh_HANT", "zh_TW", "zh_hant")),
    (ja_JP, ("ja_JP", "ja")),
    (ko_KR, ("ko_KR", "ko")),
    (de_DE, ("de_DE", "de")),
    (fr_FR, ("fr_FR", "fr")),
    (es_ES, ("es", "es_ES")),
    (it_IT, ("it_IT", "it")),
    (pl_PL, ("pl_PL", "pl")),
    # One Portuguese table answering for both countries, which is the common arrangement and
    # what the wording inside it was written for.
    (pt_PT, ("pt_PT", "pt_BR", "pt")),
    (ru_RU, ("ru_RU", "ru")),
    (vi_VN, ("vi_VN", "vi")),
)

TRANSLATIONS = {code: table.TRANSLATIONS for table, codes in _LOCALES for code in codes}

_FALLBACK = "en_US"


def _locale_candidates():
    """Every name worth trying for the language Blender is currently answering in.

    ``bpy.app.translations.locale`` is what the interface is actually drawing with, and it
    is the only one of the two that is set even when the user left the language on the
    system default.  ``preferences.view.language`` is the explicit choice, which can disagree
    with it.  Both are tried whole and then down to the language prefix, because the codes
    Blender ships are the broad ones -- Simplified Chinese is ``zh_HANS``, not ``zh_CN`` -- and
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
