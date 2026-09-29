"""Italian strings, keyed by the English sentence they replace.

Placeholders travel with the sentence, so ``{counts}`` and friends stay exactly as they are
and only the words around them move.  ``{kind}`` hangs off the masculine ``tipo`` in the
three minimum-point messages, so one pair of forms fits curva, percorso and confine alike.
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
        "Blocca la selezione, poi imposta con la rotella il numero di segmenti. Con "
        "Shift la rotella leviga la curva, con Ctrl distribuisce i punti e ogni scatto "
        "rafforza questo effetto. Il clic sinistro mantiene, il clic destro ripristina."
    ),
    (
        "*",
        "Quickly adjust the segment count of any edge:  scroll sets the count, Shift "
        "smooths the edge, Ctrl spreads the points evenly, and attributes such as "
        "UVs, seams and vertex colors survive the change intact.",
    ): (
        "Imposta rapidamente il numero di segmenti di qualsiasi spigolo: la rotella "
        "fissa i segmenti, Shift leviga lo spigolo, Ctrl distribuisce i punti e, dopo "
        "la regolazione, gli attributi come UV, cuciture e colori dei vertici restano "
        "intatti."
    ),
    # The overlay's chip row.
    ("*", "[Wheel] Segments {entry} → {current}"): "[Rotella] Segmenti {entry} → {current}",
    ("*", "[Shift] Smooth"): "[Shift] Leviga",
    ("*", "[Ctrl] Even"): "[Ctrl] Uniforma",
    ("*", "[LMB] Keep   [RMB] Revert"): "[SX] Mantieni   [DX] Ripristina",
    (
        "*",
        "Loop Resample failed safely: ",
    ): "Loop Resample non riuscito in modo sicuro: ",
    # Reports.
    ("*", "Reverted to {counts} segment(s)."): "Ripristinati {counts} segmenti.",
    (
        "*",
        "Reverted to {counts} segment(s) and the original curve.",
    ): "Ripristinati {counts} segmenti e la curva originale.",
    ("*", "Left the curve as it was."): "La curva è stata lasciata com'era.",
    (
        "*",
        "Kept {counts} segment(s) on the locked path(s).",
    ): "Mantenuti {counts} segmenti sui percorsi bloccati.",
    (
        "*",
        "Kept {counts} segment(s) and the adjusted curve on the locked path(s).",
    ): "Mantenuti {counts} segmenti e la curva regolata sui percorsi bloccati.",
    (
        "*",
        "Resampled {paths} path(s): {changes}; rebuilt {strips} strip(s) with "
        "{faces} face(s)",
    ): (
        "Ricampionati {paths} percorsi: {changes}; ricostruite {strips} strisce con "
        "{faces} facce"
    ),
    (
        "*",
        "No seam mark on {count} UV island boundary position(s), so one face there "
        "stretches across the UV map.  Mark Seam on those cuts to line them up.",
    ): (
        "Nessuna cucitura segnata su {count} posizioni di confine delle isole UV, quindi lì "
        "una faccia si allunga su tutta la mappa UV. Applica Mark Seam su quei tagli "
        "per allinearli."
    ),
    # Refusals and failures, which reach the user as the warning chip.
    ("*", "closed"): "chiuso",
    ("*", "open"): "aperto",
    (
        "*",
        "A {kind} curve needs at least {minimum} points.",
    ): "Una curva del tipo {kind} richiede almeno {minimum} punti.",
    (
        "*",
        "A {kind} path needs at least {minimum} points.",
    ): "Un percorso del tipo {kind} richiede almeno {minimum} punti.",
    (
        "*",
        "A {kind} boundary needs at least {minimum} points.",
    ): "Un confine del tipo {kind} richiede almeno {minimum} punti.",
    (
        "*",
        "A curve source contains a zero-length segment.",
    ): "Una sorgente di curva contiene un segmento di lunghezza zero.",
    (
        "*",
        "A fitted curve segment has no measurable length.",
    ): "Un segmento della curva adattata non ha una lunghezza misurabile.",
    (
        "*",
        "The fitted curve has no measurable length.",
    ): "La curva adattata nel complesso non ha una lunghezza misurabile.",
    (
        "*",
        "A boundary contains a zero-length segment.",
    ): "Un confine contiene un segmento di lunghezza zero.",
    (
        "*",
        "The strip plan contains no complete face sequence.",
    ): (
        "Il piano delle strisce non contiene alcuna sequenza completa di facce."
    ),
    (
        "*",
        "The strip plan did not consume the full inner boundary.",
    ): "Il piano delle strisce non ha esaurito per intero il confine interno.",
    (
        "*",
        "The strip plan did not consume the full outer boundary.",
    ): "Il piano delle strisce non ha esaurito per intero il confine esterno.",
    (
        "*",
        "The strip plan contains a degenerate face.",
    ): "Il piano delle strisce contiene una faccia degenerata.",
    (
        "*",
        "Select a continuous chain of edges or points.",
    ): "Seleziona una catena continua di spigoli o punti.",
    (
        "*",
        "The selected edges cross each other.  Keep only one direction of them.",
    ): "Gli spigoli selezionati si incrociano tra loro. Mantieni solo una direzione.",
    (
        "*",
        "The selected edges are not joined, so they cannot form one continuous chain.",
    ): (
        "Gli spigoli selezionati non sono uniti, quindi non possono formare una catena "
        "continua."
    ),
    (
        "*",
        "The selected edges are not continuous; there is a gap in between.",
    ): "Gli spigoli selezionati non sono continui; in mezzo c'è uno spazio.",
    (
        "*",
        "The selected edges close back into a ring.  Break the loop and try again.",
    ): "Gli spigoli selezionati si richiudono ad anello. Interrompi il ciclo e riprova.",
    (
        "*",
        "No valid ordered strip path was found.",
    ): "Non è stato trovato alcun percorso valido di strisce ordinate.",
    (
        "*",
        "The ordered strip contains intersecting edges.",
    ): "La striscia ordinata contiene spigoli che si intersecano.",
    (
        "*",
        "The inner curve has too few points.",
    ): "La curva interna ha troppo pochi punti.",
    (
        "*",
        "The outer curve has too few points.",
    ): "La curva esterna ha troppo pochi punti.",
    (
        "*",
        "The faces beside this chain all close in on one point, so it has to be "
        "resampled as a whole ring.",
    ): (
        "Le facce accanto a questa catena si chiudono tutte su un unico punto, quindi va "
        "ricampionata come anello completo."
    ),
    (
        "*",
        "This chain of edges does not run between two matching strips of faces, so "
        "there is nothing here to resample.",
    ): (
        "Questa catena di spigoli non corre tra due strisce di facce corrispondenti, quindi "
        "qui non c'è nulla da ricampionare."
    ),
    (
        "*",
        "The selected path contains a branch that cannot be resampled safely.",
    ): (
        "Il percorso selezionato contiene una diramazione che non si può ricampionare in "
        "modo sicuro."
    ),
    (
        "*",
        "The target path would duplicate an existing edge.",
    ): "Il percorso obiettivo duplicherebbe uno spigolo già esistente.",
    (
        "*",
        "The triangle-fan cap is no longer valid.",
    ): "Il tappo a ventaglio di triangoli non è più valido.",
    (
        "*",
        "An n-gon cap needs at least three boundary vertices.",
    ): "Un tappo n-gon richiede almeno tre vertici di confine.",
    (
        "*",
        "The n-gon cap boundary contains duplicate points.",
    ): "Il confine del tappo n-gon contiene punti duplicati.",
    (
        "*",
        "The n-gon cap boundary is degenerate or self-intersecting.",
    ): "Il confine del tappo n-gon è degenere o si autointerseca.",
    (
        "*",
        "The n-gon cap would contain a degenerate triangle.",
    ): "Il tappo n-gon conterrebbe un triangolo degenere.",
    (
        "*",
        "The source no longer matches the locked selection.",
    ): "La sorgente non corrisponde più alla selezione bloccata.",
    (
        "*",
        "Select one path or multiple quad-connected parallel paths.",
    ): "Seleziona un percorso, o più percorsi paralleli collegati da quad.",
    (
        "*",
        "Nothing here can be resampled.  Select a continuous chain of edges or points.",
    ): (
        "Qui non c'è nulla da ricampionare. Seleziona una catena continua di spigoli o "
        "punti."
    ),
}
