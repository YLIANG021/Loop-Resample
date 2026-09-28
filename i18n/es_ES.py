"""Spanish strings, keyed by the English sentence they replace.

Placeholders travel with the sentence, so ``{counts}`` and friends stay exactly as they are
and only the words around them move.  Spanish nouns carry a gender, so ``{kind}`` hangs off
the masculine ``bucle`` in the three minimum-point messages; that way one
``cerrado``/``abierto`` pair fits a curva, a trayectoria and a límite alike.
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
        "Bloquea la selección y usa la rueda para fijar su número de segmentos. Con "
        "Shift la rueda suaviza la curva, con Ctrl reparte sus puntos, y cada paso de "
        "rueda refuerza el efecto. Clic izquierdo lo mantiene, clic derecho lo revierte."
    ),
    (
        "*",
        "Quickly adjust the segment count of any edge:  scroll sets the count, Shift "
        "smooths the edge, Ctrl spreads the points evenly, and attributes such as "
        "UVs, seams and vertex colors survive the change intact.",
    ): (
        "Ajusta rápidamente el número de segmentos de cualquier arista: la rueda fija "
        "la cantidad, Shift suaviza la arista, Ctrl reparte sus puntos y, tras el "
        "ajuste, atributos como las UV, las costuras y los colores de vértice se "
        "conservan intactos."
    ),
    # The overlay's chip row.
    ("*", "[Wheel] Segments {entry} → {current}"): "[Rueda] Segmentos {entry} → {current}",
    ("*", "[Shift] Smooth"): "[Shift] Suave",
    ("*", "[Ctrl] Even"): "[Ctrl] Igual",
    ("*", "[LMB] Keep   [RMB] Revert"): "[Izq] Mantener   [Der] Revertir",
    ("*", "Loop Resample failed safely: "): "Loop Resample falló de forma segura: ",
    # Reports.
    ("*", "Reverted to {counts} segment(s)."): "Se revirtió a {counts} segmento(s).",
    (
        "*",
        "Reverted to {counts} segment(s) and the original curve.",
    ): "Se revirtió a {counts} segmento(s) y a la curva original.",
    (
        "*",
        "Kept {counts} segment(s) on the locked path(s).",
    ): "Se mantuvieron {counts} segmento(s) en la(s) trayectoria(s) bloqueada(s).",
    (
        "*",
        "Kept {counts} segment(s) and the adjusted curve on the locked path(s).",
    ): (
        "Se mantuvieron {counts} segmento(s) y la curva ajustada en la(s) "
        "trayectoria(s) bloqueada(s)."
    ),
    (
        "*",
        "Resampled {paths} path(s): {changes}; rebuilt {strips} strip(s) with "
        "{faces} face(s)",
    ): (
        "Se remuestrearon {paths} trayectoria(s): {changes}; se reconstruyeron "
        "{strips} banda(s) con {faces} cara(s)"
    ),
    (
        "*",
        "No seam mark on {count} UV island boundary position(s), so one face there "
        "stretches across the UV map.  Mark Seam on those cuts to line them up.",
    ): (
        "Falta la marca de costura en {count} posición(es) del límite de las islas "
        "UV, así que allí una cara se estira por todo el mapa UV. Aplica Mark Seam "
        "en esos cortes para alinearlos."
    ),
    # Refusals and failures, which reach the user as the warning chip.
    ("*", "closed"): "cerrado",
    ("*", "open"): "abierto",
    (
        "*",
        "A {kind} curve needs at least {minimum} points.",
    ): "Una curva con el bucle {kind} necesita al menos {minimum} puntos.",
    (
        "*",
        "A {kind} path needs at least {minimum} points.",
    ): "Una trayectoria con el bucle {kind} necesita al menos {minimum} puntos.",
    (
        "*",
        "A {kind} boundary needs at least {minimum} points.",
    ): "Un límite con el bucle {kind} necesita al menos {minimum} puntos.",
    (
        "*",
        "A curve source contains a zero-length segment.",
    ): "El origen de la curva contiene un segmento de longitud cero.",
    (
        "*",
        "A fitted curve segment has no measurable length.",
    ): "Un segmento de la curva ajustada no tiene longitud medible.",
    (
        "*",
        "The fitted curve has no measurable length.",
    ): "La curva ajustada no tiene longitud medible.",
    (
        "*",
        "A boundary contains a zero-length segment.",
    ): "El límite contiene un segmento de longitud cero.",
    (
        "*",
        "The strip plan contains no complete face sequence.",
    ): "El plan de bandas no contiene ninguna secuencia completa de caras.",
    (
        "*",
        "The strip plan did not consume the full inner boundary.",
    ): "El plan de bandas no agotó todo el límite interior.",
    (
        "*",
        "The strip plan did not consume the full outer boundary.",
    ): "El plan de bandas no agotó todo el límite exterior.",
    (
        "*",
        "The strip plan contains a degenerate face.",
    ): "El plan de bandas contiene una cara degenerada.",
    (
        "*",
        "Select a continuous chain of edges or points.",
    ): "Selecciona una cadena continua de aristas o puntos.",
    (
        "*",
        "The selected edges cross each other.  Keep only one direction of them.",
    ): "Las aristas seleccionadas se cruzan. Mantén solo una de las direcciones.",
    (
        "*",
        "The selected edges are not joined, so they cannot form one continuous chain.",
    ): (
        "Las aristas seleccionadas no están unidas, así que no pueden formar una "
        "cadena continua."
    ),
    (
        "*",
        "The selected edges are not continuous; there is a gap in between.",
    ): "Las aristas seleccionadas no son continuas; hay un hueco entre ellas.",
    (
        "*",
        "The selected edges close back into a ring.  Break the loop and try again.",
    ): (
        "Las aristas seleccionadas se cierran en un anillo. Rompe el bucle e "
        "inténtalo de nuevo."
    ),
    (
        "*",
        "No valid ordered strip path was found.",
    ): "No se encontró ninguna trayectoria válida de banda ordenada.",
    (
        "*",
        "The ordered strip contains intersecting edges.",
    ): "La banda ordenada contiene aristas que se cruzan.",
    ("*", "The inner curve has too few points."): "La curva interior tiene muy pocos puntos.",
    ("*", "The outer curve has too few points."): "La curva exterior tiene muy pocos puntos.",
    (
        "*",
        "The faces beside this chain all close in on one point, so it has to be "
        "resampled as a whole ring.",
    ): (
        "Las caras junto a esta cadena convergen todas en un mismo punto, así que "
        "hay que remuestrearla como un anillo completo."
    ),
    (
        "*",
        "This chain of edges does not run between two matching strips of faces, so "
        "there is nothing here to resample.",
    ): (
        "Esta cadena de aristas no discurre entre dos bandas de caras que "
        "coincidan, así que aquí no hay nada que remuestrear."
    ),
    (
        "*",
        "The selected path contains a branch that cannot be resampled safely.",
    ): (
        "La trayectoria seleccionada contiene una bifurcación que no se puede "
        "remuestrear de forma segura."
    ),
    (
        "*",
        "The target path would duplicate an existing edge.",
    ): "La trayectoria objetivo duplicaría una arista existente.",
    (
        "*",
        "The triangle-fan cap is no longer valid.",
    ): "La tapa de abanico de triángulos ya no es válida.",
    (
        "*",
        "An n-gon cap needs at least three boundary vertices.",
    ): "Una tapa n-gon necesita al menos tres vértices en el límite.",
    (
        "*",
        "The n-gon cap boundary contains duplicate points.",
    ): "El límite de la tapa n-gon contiene puntos duplicados.",
    (
        "*",
        "The n-gon cap boundary is degenerate or self-intersecting.",
    ): "El límite de la tapa n-gon es degenerado o se cruza consigo mismo.",
    (
        "*",
        "The n-gon cap would contain a degenerate triangle.",
    ): "La tapa n-gon contendría un triángulo degenerado.",
    (
        "*",
        "The source no longer matches the locked selection.",
    ): "El origen ya no coincide con la selección bloqueada.",
    (
        "*",
        "Select one path or multiple quad-connected parallel paths.",
    ): (
        "Selecciona una trayectoria o varias trayectorias paralelas unidas por "
        "cuadriláteros."
    ),
    (
        "*",
        "Nothing here can be resampled.  Select a continuous chain of edges or points.",
    ): (
        "Aquí no se puede remuestrear nada. Selecciona una cadena continua de "
        "aristas o puntos."
    ),
}
