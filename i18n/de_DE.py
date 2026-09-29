"""German strings, keyed by the English sentence they replace.

The wording follows Blender's own German UI terms, and resampling is "neu abtasten"
everywhere.  Placeholders travel with the sentence, so ``{counts}`` and friends stay
exactly as they are and only the words around them move.
"""

TRANSLATIONS = {
    # Operator tooltips.  The two operator names are not here on purpose: they stay English
    # in every locale.
    (
        "*",
        "Lock the selection, then scroll to set its segment count.  Shift scrolls smooth "
        "the curve, Ctrl scrolls spread its points, and each tick strengthens that effect.  "
        "Left-click keeps it, right-click reverts.",
    ): (
        "Auswahl sperren, dann mit dem Rad die Segmentanzahl einstellen. Mit Shift glättet "
        "das Rad die Kurve, mit Ctrl verteilt es ihre Punkte, und jede Raste verstärkt "
        "diesen Effekt. Linksklick behält das Ergebnis, Rechtsklick setzt es zurück."
    ),
    (
        "*",
        "Quickly adjust the segment count of any edge:  scroll sets the count, Shift "
        "smooths the edge, Ctrl spreads the points evenly, and attributes such as "
        "UVs, seams and vertex colors survive the change intact.",
    ): (
        "Die Segmentanzahl beliebiger Kanten schnell anpassen: Das Rad stellt die "
        "Segmentanzahl ein, mit Shift wird die Kante geglättet, mit Ctrl werden ihre "
        "Punkte verteilt, und Attribute wie UVs, Nähte und Eckenfarben bleiben nach "
        "der Anpassung vollständig erhalten."
    ),
    # The overlay's chip row.
    ("*", "[Wheel] Segments {entry} → {current}"): "[Rad] Segmente {entry} → {current}",
    ("*", "[Shift] Smooth"): "[Shift] Glätten",
    ("*", "[Ctrl] Even"): "[Ctrl] Gleich",
    ("*", "[LMB] Keep   [RMB] Revert"): "[Links] Behalten   [Rechts] Zurück",
    ("*", "Loop Resample failed safely: "): "Loop Resample sicher fehlgeschlagen: ",
    # Reports.
    ("*", "Reverted to {counts} segment(s)."): "Auf {counts} Segment(e) zurückgesetzt.",
    (
        "*",
        "Reverted to {counts} segment(s) and the original curve.",
    ): "Auf {counts} Segment(e) und die ursprüngliche Kurve zurückgesetzt.",
    ("*", "Left the curve as it was."): "Die Kurve wurde nicht verändert.",
    ("*", "Kept {counts} segment(s) on the locked path(s)."): (
        "{counts} Segment(e) auf gesperrtem Pfad behalten."
    ),
    (
        "*",
        "Kept {counts} segment(s) and the adjusted curve on the locked path(s).",
    ): "{counts} Segment(e) und die angepasste Kurve auf gesperrtem Pfad behalten.",
    (
        "*",
        "Resampled {paths} path(s): {changes}; rebuilt {strips} strip(s) with "
        "{faces} face(s)",
    ): (
        "{paths} Pfad(e) neu abgetastet: {changes}; {strips} Streifen mit "
        "{faces} Fläche(n) neu aufgebaut"
    ),
    (
        "*",
        "No seam mark on {count} UV island boundary position(s), so one face there "
        "stretches across the UV map.  Mark Seam on those cuts to line them up.",
    ): (
        "An {count} Position(en) der UV-Inselbegrenzung fehlt eine Naht, wodurch dort "
        "eine Fläche über die ganze UV-Map gedehnt wird. Mark Seam auf diese Schnitte "
        "setzen, damit sie sich ausrichten."
    ),
    # Refusals and failures, which reach the user as the warning chip.
    ("*", "closed"): "geschlossene",
    ("*", "open"): "offene",
    ("*", "A {kind} curve needs at least {minimum} points."): (
        "Die {kind} Kurve benötigt mindestens {minimum} Punkte."
    ),
    ("*", "A {kind} path needs at least {minimum} points."): (
        "Der {kind} Pfad benötigt mindestens {minimum} Punkte."
    ),
    ("*", "A {kind} boundary needs at least {minimum} points."): (
        "Die {kind} Begrenzung benötigt mindestens {minimum} Punkte."
    ),
    ("*", "A curve source contains a zero-length segment."): (
        "Die Kurvenquelle enthält ein Segment der Länge null."
    ),
    (
        "*",
        "A fitted curve segment has no measurable length.",
    ): "Ein Segment der angepassten Kurve hat keine messbare Länge.",
    ("*", "The fitted curve has no measurable length."): (
        "Die angepasste Kurve hat keine messbare Länge."
    ),
    ("*", "A boundary contains a zero-length segment."): (
        "Die Begrenzung enthält ein Segment der Länge null."
    ),
    ("*", "The strip plan contains no complete face sequence."): (
        "Der Streifenplan enthält keine vollständige Flächensequenz."
    ),
    (
        "*",
        "The strip plan did not consume the full inner boundary.",
    ): "Der Streifenplan hat die innere Begrenzung nicht vollständig erfasst.",
    (
        "*",
        "The strip plan did not consume the full outer boundary.",
    ): "Der Streifenplan hat die äußere Begrenzung nicht vollständig erfasst.",
    ("*", "The strip plan contains a degenerate face."): (
        "Der Streifenplan enthält eine entartete Fläche."
    ),
    ("*", "Select a continuous chain of edges or points."): (
        "Eine durchgehende Kette aus Kanten oder Punkten auswählen."
    ),
    (
        "*",
        "The selected edges cross each other.  Keep only one direction of them.",
    ): "Die ausgewählten Kanten kreuzen sich. Nur eine Richtung davon behalten.",
    (
        "*",
        "The selected edges are not joined, so they cannot form one continuous chain.",
    ): (
        "Die ausgewählten Kanten sind nicht verbunden, sie können daher keine "
        "durchgehende Kette bilden."
    ),
    (
        "*",
        "The selected edges are not continuous; there is a gap in between.",
    ): "Die ausgewählten Kanten sind nicht durchgehend; dazwischen klafft eine Lücke.",
    (
        "*",
        "The selected edges close back into a ring.  Break the loop and try again.",
    ): (
        "Die ausgewählten Kanten schließen sich zu einem Ring. Schleife "
        "unterbrechen und erneut versuchen."
    ),
    ("*", "No valid ordered strip path was found."): (
        "Kein gültiger geordneter Streifenpfad gefunden."
    ),
    ("*", "The ordered strip contains intersecting edges."): (
        "Der geordnete Streifen enthält sich schneidende Kanten."
    ),
    ("*", "The inner curve has too few points."): "Die innere Kurve hat zu wenige Punkte.",
    ("*", "The outer curve has too few points."): "Die äußere Kurve hat zu wenige Punkte.",
    (
        "*",
        "The faces beside this chain all close in on one point, so it has to be "
        "resampled as a whole ring.",
    ): (
        "Die Flächen neben dieser Kette laufen alle auf einen Punkt zu, daher muss sie als "
        "ganzer Ring neu abgetastet werden."
    ),
    (
        "*",
        "This chain of edges does not run between two matching strips of faces, so "
        "there is nothing here to resample.",
    ): (
        "Diese Kantenkette verläuft nicht zwischen zwei passenden Flächenstreifen, daher "
        "kann hier nichts neu abgetastet werden."
    ),
    (
        "*",
        "The selected path contains a branch that cannot be resampled safely.",
    ): (
        "Der ausgewählte Pfad enthält eine Verzweigung, die sich nicht sicher "
        "neu abtasten lässt."
    ),
    ("*", "The target path would duplicate an existing edge."): (
        "Der Zielpfad würde eine vorhandene Kante duplizieren."
    ),
    ("*", "The triangle-fan cap is no longer valid."): (
        "Die Dreiecksfächer-Kappe ist nicht mehr gültig."
    ),
    ("*", "An n-gon cap needs at least three boundary vertices."): (
        "Eine n-gon-Kappe benötigt mindestens drei Begrenzungspunkte."
    ),
    ("*", "The n-gon cap boundary contains duplicate points."): (
        "Die Begrenzung der n-gon-Kappe enthält doppelte Punkte."
    ),
    (
        "*",
        "The n-gon cap boundary is degenerate or self-intersecting.",
    ): "Die Begrenzung der n-gon-Kappe ist entartet oder schneidet sich selbst.",
    ("*", "The n-gon cap would contain a degenerate triangle."): (
        "Die n-gon-Kappe würde ein entartetes Dreieck enthalten."
    ),
    ("*", "The source no longer matches the locked selection."): (
        "Die Quelle stimmt nicht mehr mit der gesperrten Auswahl überein."
    ),
    (
        "*",
        "Select one path or multiple quad-connected parallel paths.",
    ): "Entweder einen Pfad auswählen oder mehrere über Vierecke verbundene parallele Pfade.",
    (
        "*",
        "Nothing here can be resampled.  Select a continuous chain of edges or points.",
    ): (
        "Hier kann nichts neu abgetastet werden. Eine durchgehende Kette aus Kanten oder "
        "Punkten auswählen."
    ),
    # Why the menu item is greyed out, and what a wheel that never started says.
    (
        "*",
        "Only available in mesh Edit Mode, with the vertex or edge select mode turned on.",
    ): (
        "Nur im Bearbeiten-Modus eines Netzes verfügbar, wenn die Auswahl auf Eckpunkte oder Kanten steht."
    ),
    (
        "*",
        "The wheel could not start: this viewport no longer has a mesh to adjust.",
    ): (
        "Das Mausrad konnte nicht gestartet werden: Diese 3D-Ansicht enthält kein Netz zum Anpassen mehr."
    ),
}
