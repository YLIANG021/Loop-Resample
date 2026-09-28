"""The English source strings, listed once so the other locales can be checked against them.

Every sentence here is also the key it is looked up by, which is why this file is a list
rather than a dictionary of identities: adding a string to the interface means adding it
here, and a locale that has not caught up simply answers with the English.
"""

MESSAGES = [
    # Operator tooltips.  The two operator names are deliberately absent: they stay English
    # in every locale, so there is nothing here for a locale to answer.
    (
        "Lock the selection, then scroll to set its segment count.  Shift scrolls smooth "
        "the curve, Ctrl scrolls spread its points, and each tick strengthens that effect.  "
        "Left-click keeps it, right-click reverts."
    ),
    (
        "Quickly adjust the segment count of any edge:  scroll sets the count, Shift "
        "smooths the edge, Ctrl spreads the points evenly, and attributes such as "
        "UVs, seams and vertex colors survive the change intact."
    ),
    # The overlay's chip row.
    "[Wheel] Segments {entry} → {current}",
    "[Shift] Smooth",
    "[Ctrl] Even",
    "[LMB] Keep   [RMB] Revert",
    "Loop Resample failed safely: ",
    # Reports.
    "Reverted to {counts} segment(s).",
    "Reverted to {counts} segment(s) and the original curve.",
    "Kept {counts} segment(s) on the locked path(s).",
    "Kept {counts} segment(s) and the adjusted curve on the locked path(s).",
    "Resampled {paths} path(s): {changes}; rebuilt {strips} strip(s) with {faces} face(s)",
    "No seam mark on {count} UV island boundary position(s), so one face there "
    "stretches across the UV map.  Mark Seam on those cuts to line them up.",
    # Refusals and failures, which reach the user as the warning chip.
    "closed",
    "open",
    "A {kind} curve needs at least {minimum} points.",
    "A {kind} path needs at least {minimum} points.",
    "A {kind} boundary needs at least {minimum} points.",
    "A curve source contains a zero-length segment.",
    "A fitted curve segment has no measurable length.",
    "The fitted curve has no measurable length.",
    "A boundary contains a zero-length segment.",
    "The strip plan contains no complete face sequence.",
    "The strip plan did not consume the full inner boundary.",
    "The strip plan did not consume the full outer boundary.",
    "The strip plan contains a degenerate face.",
    "Select a continuous chain of edges or points.",
    "The selected edges cross each other.  Keep only one direction of them.",
    "The selected edges are not joined, so they cannot form one continuous chain.",
    "The selected edges are not continuous; there is a gap in between.",
    "The selected edges close back into a ring.  Break the loop and try again.",
    "No valid ordered strip path was found.",
    "The ordered strip contains intersecting edges.",
    "The inner curve has too few points.",
    "The outer curve has too few points.",
    (
        "The faces beside this chain all close in on one point, so it has to be "
        "resampled as a whole ring."
    ),
    (
        "This chain of edges does not run between two matching strips of faces, so "
        "there is nothing here to resample."
    ),
    "The selected path contains a branch that cannot be resampled safely.",
    "The target path would duplicate an existing edge.",
    "The triangle-fan cap is no longer valid.",
    "An n-gon cap needs at least three boundary vertices.",
    "The n-gon cap boundary contains duplicate points.",
    "The n-gon cap boundary is degenerate or self-intersecting.",
    "The n-gon cap would contain a degenerate triangle.",
    "The source no longer matches the locked selection.",
    "Select one path or multiple quad-connected parallel paths.",
    (
        "Nothing here can be resampled.  Select a continuous chain of edges or points."
    ),
]

TRANSLATIONS = {("*", message): message for message in MESSAGES}
