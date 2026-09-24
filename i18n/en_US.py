"""The English source strings, listed once so the other locales can be checked against them.

Every sentence here is also the key it is looked up by, which is why this file is a list
rather than a dictionary of identities: adding a string to the interface means adding it
here, and a locale that has not caught up simply answers with the English.
"""

MESSAGES = [
    # Operator names and tooltips.
    "Adjust Resample by Wheel",
    (
        "Lock what is selected, then scroll to set its segment count.  Hold Shift and "
        "scroll to smooth the locked curve(s), or Ctrl and scroll to spread their points "
        "more evenly -- every tick strengthens whichever effect the held key armed, and "
        "left-click keeps it while right-click goes back to what was there before"
    ),
    "Adjust Loops by Wheel",
    "Enter Loop Resample",
    "Lock the current mesh and selection as the resample source",
    "Loop Resample",
    "Resample the locked paths from the session source",
    "Confirm Resample",
    "Keep the current result and end the session",
    "Cancel Resample",
    "Restore the mesh to its state when the session started",
    # The overlay's chip row.
    "[Wheel] Segments {entry} → {current}",
    "[Shift] Smooth",
    "[Ctrl] Even",
    "[LMB] Keep   [RMB] Revert",
    "Loop Resample failed safely: ",
    # Reports.
    "Locked {count} path(s): {counts}",
    "Mesh update is already running; wait a moment.",
    "Enter adjust mode first.",
    "Restored the mesh from before the session.",
    "Reverted to {counts} segment(s).",
    "Reverted to {counts} segment(s) and the original curve.",
    "Kept {counts} segment(s) on the locked path(s).",
    "Kept {counts} segment(s) and the adjusted curve on the locked path(s).",
    "Resampled {paths} path(s): {changes}; rebuilt {strips} strip(s) with {faces} face(s)",
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
    "The target count cannot preserve every feature anchor.",
    "Feature anchors do not span a valid boundary.",
    "Feature-aware sampling returned the wrong point count.",
    "The strip plan contains no complete face sequence.",
    "The strip plan did not consume the full inner boundary.",
    "The strip plan did not consume the full outer boundary.",
    "The strip plan contains a degenerate face.",
    "Select one continuous edge chain or edge loop.",
    (
        "The selection branches at point {where}: a path can only run through points "
        "that join one or two selected edges."
    ),
    "The selected edges form neither one open chain nor one closed loop.",
    (
        "{count} of the selected edges are not joined to this chain, so the selection "
        "is broken in between."
    ),
    "The selected edges do not run end to end as one open chain.",
    "No valid ordered strip path was found.",
    "The ordered strip contains intersecting edges.",
    "The inner curve has too few points.",
    "The outer curve has too few points.",
    (
        "{attached} of {total} rail edges still hold faces the capture left out "
        "(edge {edge} holds face {face}): the selected path does not run between two "
        "supported strips."
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
        "Nothing here can be resampled.  Select a continuous chain of edges, a closed "
        "edge loop, or a row of points that edges run through."
    ),
]

TRANSLATIONS = {("*", message): message for message in MESSAGES}
