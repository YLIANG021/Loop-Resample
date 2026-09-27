"""Polish strings, keyed by the English sentence they replace.

The keys are the English sentences themselves, so a string this table does not answer just
falls back to English.  Placeholders travel with the sentence: ``{counts}`` and friends stay
exactly as they are and only the Polish words around them move.  Polish writes one space,
not two, after a full stop.
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
        "Zablokuj zaznaczenie, a potem kręć rolką, aby ustawić liczbę segmentów. "
        "Kręcenie z Shift wygładza krzywą, z Ctrl rozkłada jej punkty równomiernie, "
        "a każda działka wzmacnia ten efekt. Kliknięcie LPM zachowuje, PPM przywraca."
    ),
    ("*", "Enter Loop Resample"): "Rozpocznij resampling pętli",
    ("*", "Lock the current mesh and selection as the resample source"): (
        "Zablokuj bieżącą siatkę i zaznaczenie jako źródło resamplingu"
    ),
    ("*", "Loop Resample"): "Resampling pętli",
    ("*", "Resample the locked paths from the session source"): (
        "Resampluj zablokowane ścieżki ze źródła sesji"
    ),
    ("*", "Confirm Resample"): "Potwierdź resampling",
    ("*", "Keep the current result and end the session"): (
        "Zachowaj bieżący wynik i zakończ sesję"
    ),
    ("*", "Cancel Resample"): "Anuluj resampling",
    ("*", "Restore the mesh to its state when the session started"): (
        "Przywróć siatkę do stanu z początku sesji"
    ),
    # The overlay's chip row.
    ("*", "[Wheel] Segments {entry} → {current}"): "[Rolka] Segmenty {entry} → {current}",
    ("*", "[Shift] Smooth"): "[Shift] Gładko",
    ("*", "[Ctrl] Even"): "[Ctrl] Równo",
    ("*", "[LMB] Keep   [RMB] Revert"): "[LPM] Zachowaj   [PPM] Przywróć",
    ("*", "Loop Resample failed safely: "): (
        "Bezpiecznie przerwano resampling pętli: "
    ),
    # Reports.
    ("*", "Locked {count} path(s): {counts}"): "Zablokowano ścieżki ({count}): {counts}",
    ("*", "Mesh update is already running; wait a moment."): (
        "Aktualizacja siatki już trwa; odczekaj chwilę."
    ),
    ("*", "Enter adjust mode first."): "Najpierw przejdź do trybu dostosowywania.",
    ("*", "Restored the mesh from before the session."): "Przywrócono siatkę sprzed sesji.",
    ("*", "Reverted to {counts} segment(s)."): "Przywrócono segmenty: {counts}.",
    ("*", "Reverted to {counts} segment(s) and the original curve."): (
        "Przywrócono segmenty: {counts} oraz oryginalną krzywą."
    ),
    ("*", "Kept {counts} segment(s) on the locked path(s)."): (
        "Na zablokowanych ścieżkach zachowano segmenty: {counts}."
    ),
    (
        "*",
        "Kept {counts} segment(s) and the adjusted curve on the locked path(s).",
    ): (
        "Na zablokowanych ścieżkach zachowano segmenty: {counts} oraz dostosowaną krzywą."
    ),
    (
        "*",
        "Resampled {paths} path(s): {changes}; rebuilt {strips} strip(s) with "
        "{faces} face(s)",
    ): (
        "Resamplowano ścieżki ({paths}): {changes}; przebudowano paski ({strips}), "
        "lica: {faces}"
    ),
    (
        "*",
        "No seam mark on {count} UV island boundary position(s), so one face there "
        "stretches across the UV map.  Mark Seam on those cuts to line them up.",
    ): (
        "Brak oznaczenia szwu na pozycjach granicy wysp UV ({count}), więc jedno lico "
        "rozciąga się tam przez całą mapę UV. Ustaw Mark Seam na tych cięciach, aby się "
        "wyrównały."
    ),
    # Refusals and failures, which reach the user as the warning chip.
    ("*", "closed"): "zamknięta",
    ("*", "open"): "otwarta",
    ("*", "A {kind} curve needs at least {minimum} points."): (
        "Krzywa {kind} wymaga co najmniej {minimum} punktów."
    ),
    ("*", "A {kind} path needs at least {minimum} points."): (
        "Ścieżka {kind} wymaga co najmniej {minimum} punktów."
    ),
    ("*", "A {kind} boundary needs at least {minimum} points."): (
        "Granica {kind} wymaga co najmniej {minimum} punktów."
    ),
    ("*", "A curve source contains a zero-length segment."): (
        "Źródło krzywej zawiera segment o zerowej długości."
    ),
    ("*", "A fitted curve segment has no measurable length."): (
        "Segment dopasowanej krzywej nie ma mierzalnej długości."
    ),
    ("*", "The fitted curve has no measurable length."): (
        "Dopasowana krzywa nie ma mierzalnej długości."
    ),
    ("*", "A boundary contains a zero-length segment."): (
        "Granica zawiera segment o zerowej długości."
    ),
    ("*", "The target count cannot preserve every feature anchor."): (
        "Docelowa liczba segmentów nie pozwala zachować każdej kotwicy cech."
    ),
    ("*", "Feature anchors do not span a valid boundary."): (
        "Kotwice cech nie wyznaczają prawidłowej granicy."
    ),
    (
        "*",
        "Feature-aware sampling returned the wrong point count.",
    ): "Próbkowanie uwzględniające cechy zwróciło nieprawidłową liczbę punktów.",
    ("*", "The strip plan contains no complete face sequence."): (
        "Plan pasków nie zawiera żadnej pełnej sekwencji lic."
    ),
    ("*", "The strip plan did not consume the full inner boundary."): (
        "Plan pasków nie pokrył całej wewnętrznej granicy."
    ),
    ("*", "The strip plan did not consume the full outer boundary."): (
        "Plan pasków nie pokrył całej zewnętrznej granicy."
    ),
    ("*", "The strip plan contains a degenerate face."): (
        "Plan pasków zawiera zdegenerowane lico."
    ),
    ("*", "Select a continuous chain of edges or points."): (
        "Wybierz ciągły łańcuch krawędzi lub punktów."
    ),
    (
        "*",
        "The selected edges cross each other.  Keep only one direction of them.",
    ): "Wybrane krawędzie przecinają się. Zachowaj tylko jeden ich kierunek.",
    (
        "*",
        "The selected edges are not joined, so they cannot form one continuous chain.",
    ): (
        "Wybrane krawędzie nie są ze sobą połączone, więc nie tworzą jednego ciągłego "
        "łańcucha."
    ),
    (
        "*",
        "The selected edges are not continuous; there is a gap in between.",
    ): "Wybrane krawędzie nie są ciągłe; jest między nimi przerwa.",
    (
        "*",
        "The selected edges close back into a ring.  Break the loop and try again.",
    ): "Wybrane krawędzie zamykają się w pierścień. Przerwij pętlę i spróbuj ponownie.",
    ("*", "No valid ordered strip path was found."): (
        "Nie znaleziono prawidłowej uporządkowanej ścieżki paska."
    ),
    ("*", "The ordered strip contains intersecting edges."): (
        "Uporządkowany pasek zawiera przecinające się krawędzie."
    ),
    ("*", "The inner curve has too few points."): "Wewnętrzna krzywa ma za mało punktów.",
    ("*", "The outer curve has too few points."): "Zewnętrzna krzywa ma za mało punktów.",
    (
        "*",
        "The faces beside this chain all close in on one point, so it has to be "
        "resampled as a whole ring.",
    ): (
        "Lica przy tym łańcuchu zbiegają się w jednym punkcie, więc trzeba go "
        "resamplować jako cały pierścień."
    ),
    (
        "*",
        "This chain of edges does not run between two matching strips of faces, so "
        "there is nothing here to resample.",
    ): (
        "Ten łańcuch krawędzi nie biegnie między dwoma odpowiadającymi sobie paskami "
        "lic, więc nie ma tu czego resamplować."
    ),
    (
        "*",
        "The selected path contains a branch that cannot be resampled safely.",
    ): "Wybrana ścieżka zawiera rozgałęzienie, którego nie da się bezpiecznie resamplować.",
    ("*", "The target path would duplicate an existing edge."): (
        "Docelowa ścieżka powieliłaby istniejącą krawędź."
    ),
    ("*", "The triangle-fan cap is no longer valid."): (
        "Zaślepienie wachlarzem trójkątów nie jest już prawidłowe."
    ),
    ("*", "An n-gon cap needs at least three boundary vertices."): (
        "Zaślepienie n-gon wymaga co najmniej trzech wierzchołków granicy."
    ),
    ("*", "The n-gon cap boundary contains duplicate points."): (
        "Granica zaślepienia n-gon zawiera zduplikowane punkty."
    ),
    ("*", "The n-gon cap boundary is degenerate or self-intersecting."): (
        "Granica zaślepienia n-gon jest zdegenerowana lub przecina samą siebie."
    ),
    ("*", "The n-gon cap would contain a degenerate triangle."): (
        "Zaślepienie n-gon zawierałoby zdegenerowany trójkąt."
    ),
    ("*", "The source no longer matches the locked selection."): (
        "Źródło nie pasuje już do zablokowanego zaznaczenia."
    ),
    (
        "*",
        "Select one path or multiple quad-connected parallel paths.",
    ): "Wybierz jedną ścieżkę lub wiele równoległych ścieżek połączonych czworokątami.",
    (
        "*",
        "Nothing here can be resampled.  Select a continuous chain of edges or points.",
    ): "Nie ma tu nic do resamplowania. Wybierz ciągły łańcuch krawędzi lub punktów.",
}
