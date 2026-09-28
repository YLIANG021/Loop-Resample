"""French strings, keyed by the English sentence they replace.

Placeholders travel with the sentence, so ``{counts}`` and friends stay exactly as they are
and only the words around them move.  French puts one space between sentences, and a space
before the colon and the semicolon.
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
        "Verrouiller la sélection, puis faire défiler la molette pour régler le nombre de "
        "segments : avec Shift la molette lisse la courbe, avec Ctrl elle répartit ses "
        "points, et chaque cran renforce cet effet. Clic gauche pour garder, clic droit "
        "pour revenir."
    ),
    ("*", "Enter Loop Resample"): "Activer le rééchantillonnage de boucle",
    (
        "*",
        "Lock the current mesh and selection as the resample source",
    ): (
        "Verrouiller le maillage et la sélection actuels comme source de rééchantillonnage"
    ),
    ("*", "Loop Resample"): "Rééchantillonnage de boucle",
    (
        "*",
        "Resample the locked paths from the session source",
    ): "Rééchantillonner les chemins verrouillés à partir de la source de la session",
    ("*", "Confirm Resample"): "Confirmer le rééchantillonnage",
    (
        "*",
        "Keep the current result and end the session",
    ): "Garder le résultat actuel et terminer la session",
    ("*", "Cancel Resample"): "Annuler le rééchantillonnage",
    (
        "*",
        "Restore the mesh to its state when the session started",
    ): "Restaurer le maillage dans son état du début de la session",
    # The overlay's chip row.
    ("*", "[Wheel] Segments {entry} → {current}"): "[Molette] Segments {entry} → {current}",
    ("*", "[Shift] Smooth"): "[Shift] Lisser",
    ("*", "[Ctrl] Even"): "[Ctrl] Égal",
    ("*", "[LMB] Keep   [RMB] Revert"): "[Clic G] Garder   [Clic D] Retour",
    ("*", "Loop Resample failed safely: "): (
        "Échec sans risque du rééchantillonnage de boucle : "
    ),
    # Reports.
    ("*", "Locked {count} path(s): {counts}"): "{count} chemin(s) verrouillé(s) : {counts}",
    ("*", "Mesh update is already running; wait a moment."): (
        "Une mise à jour du maillage est déjà en cours ; patientez un instant."
    ),
    ("*", "Enter adjust mode first."): "Activez d'abord le mode d'ajustement.",
    ("*", "Restored the mesh from before the session."): (
        "Maillage restauré dans son état d'avant la session."
    ),
    ("*", "Reverted to {counts} segment(s)."): "Retour à {counts} segment(s).",
    ("*", "Reverted to {counts} segment(s) and the original curve."): (
        "Retour à {counts} segment(s) et à la courbe d'origine."
    ),
    ("*", "Kept {counts} segment(s) on the locked path(s)."): (
        "{counts} segment(s) gardés sur le(s) chemin(s) verrouillé(s)."
    ),
    (
        "*",
        "Kept {counts} segment(s) and the adjusted curve on the locked path(s).",
    ): (
        "{counts} segment(s) et la courbe ajustée gardés sur le(s) chemin(s) verrouillé(s)."
    ),
    (
        "*",
        "Resampled {paths} path(s): {changes}; rebuilt {strips} strip(s) with "
        "{faces} face(s)",
    ): (
        "Rééchantillonné {paths} chemin(s) : {changes} ; {strips} bande(s) reconstruite(s) "
        "avec {faces} face(s)"
    ),
    (
        "*",
        "No seam mark on {count} UV island boundary position(s), so one face there "
        "stretches across the UV map.  Mark Seam on those cuts to line them up.",
    ): (
        "Aucune marque de couture sur {count} position(s) de bordure d'îlot UV ; une face "
        "s'y étire donc sur toute la carte UV. Appliquez Mark Seam sur ces découpes pour "
        "les aligner."
    ),
    # Refusals and failures, which reach the user as the warning chip.
    ("*", "closed"): "fermé",
    ("*", "open"): "ouvert",
    ("*", "A {kind} curve needs at least {minimum} points."): (
        "Une courbe de type {kind} nécessite au moins {minimum} points."
    ),
    ("*", "A {kind} path needs at least {minimum} points."): (
        "Un chemin de type {kind} nécessite au moins {minimum} points."
    ),
    ("*", "A {kind} boundary needs at least {minimum} points."): (
        "Une bordure de type {kind} nécessite au moins {minimum} points."
    ),
    ("*", "A curve source contains a zero-length segment."): (
        "Une source de courbe contient un segment de longueur nulle."
    ),
    ("*", "A fitted curve segment has no measurable length."): (
        "Un segment de la courbe ajustée n'a aucune longueur mesurable."
    ),
    ("*", "The fitted curve has no measurable length."): (
        "La courbe ajustée n'a aucune longueur mesurable."
    ),
    ("*", "A boundary contains a zero-length segment."): (
        "Une bordure contient un segment de longueur nulle."
    ),
    ("*", "The strip plan contains no complete face sequence."): (
        "Le plan de bandes ne contient aucune séquence complète de faces."
    ),
    ("*", "The strip plan did not consume the full inner boundary."): (
        "Le plan de bandes n'a pas couvert toute la bordure interne."
    ),
    ("*", "The strip plan did not consume the full outer boundary."): (
        "Le plan de bandes n'a pas couvert toute la bordure externe."
    ),
    ("*", "The strip plan contains a degenerate face."): (
        "Le plan de bandes contient une face dégénérée."
    ),
    ("*", "Select a continuous chain of edges or points."): (
        "Sélectionnez une chaîne continue d'arêtes ou de points."
    ),
    (
        "*",
        "The selected edges cross each other.  Keep only one direction of them.",
    ): "Les arêtes sélectionnées se croisent. Ne gardez qu'une seule direction.",
    (
        "*",
        "The selected edges are not joined, so they cannot form one continuous chain.",
    ): (
        "Les arêtes sélectionnées ne sont pas reliées, elles ne peuvent donc pas former "
        "une seule chaîne continue."
    ),
    (
        "*",
        "The selected edges are not continuous; there is a gap in between.",
    ): "Les arêtes sélectionnées ne sont pas continues ; un espace les sépare.",
    (
        "*",
        "The selected edges close back into a ring.  Break the loop and try again.",
    ): "Les arêtes sélectionnées se referment en anneau. Rompez la boucle et réessayez.",
    ("*", "No valid ordered strip path was found."): (
        "Aucun chemin de bande ordonnée valide n'a été trouvé."
    ),
    ("*", "The ordered strip contains intersecting edges."): (
        "La bande ordonnée contient des arêtes qui s'intersectent."
    ),
    ("*", "The inner curve has too few points."): (
        "La courbe interne compte trop peu de points."
    ),
    ("*", "The outer curve has too few points."): (
        "La courbe externe compte trop peu de points."
    ),
    (
        "*",
        "The faces beside this chain all close in on one point, so it has to be "
        "resampled as a whole ring.",
    ): (
        "Toutes les faces voisines de cette chaîne convergent vers un seul point : la "
        "chaîne doit donc être rééchantillonnée comme un anneau complet."
    ),
    (
        "*",
        "This chain of edges does not run between two matching strips of faces, so "
        "there is nothing here to resample.",
    ): (
        "Cette chaîne d'arêtes ne passe pas entre deux bandes de faces correspondantes, "
        "il n'y a donc rien à rééchantillonner ici."
    ),
    (
        "*",
        "The selected path contains a branch that cannot be resampled safely.",
    ): (
        "Le chemin sélectionné contient une bifurcation qui ne peut pas être "
        "rééchantillonnée sans risque."
    ),
    ("*", "The target path would duplicate an existing edge."): (
        "Le chemin cible dupliquerait une arête existante."
    ),
    ("*", "The triangle-fan cap is no longer valid."): (
        "Le bouchon en éventail de triangles n'est plus valide."
    ),
    ("*", "An n-gon cap needs at least three boundary vertices."): (
        "Un bouchon n-gon nécessite au moins trois sommets de bordure."
    ),
    ("*", "The n-gon cap boundary contains duplicate points."): (
        "La bordure du bouchon n-gon contient des points dupliqués."
    ),
    ("*", "The n-gon cap boundary is degenerate or self-intersecting."): (
        "La bordure du bouchon n-gon est dégénérée ou auto-intersectée."
    ),
    ("*", "The n-gon cap would contain a degenerate triangle."): (
        "Le bouchon n-gon contiendrait un triangle dégénéré."
    ),
    ("*", "The source no longer matches the locked selection."): (
        "La source ne correspond plus à la sélection verrouillée."
    ),
    (
        "*",
        "Select one path or multiple quad-connected parallel paths.",
    ): "Sélectionnez un chemin, ou plusieurs chemins parallèles reliés par des quads.",
    (
        "*",
        "Nothing here can be resampled.  Select a continuous chain of edges or points.",
    ): (
        "Ici, rien ne peut être rééchantillonné. Sélectionnez une chaîne continue "
        "d'arêtes ou de points."
    ),
}
