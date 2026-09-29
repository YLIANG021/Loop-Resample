"""Russian strings, keyed by the English sentence they replace.

Placeholders travel with the sentence, so ``{counts}`` and friends stay exactly as they are
and only the words around them move.
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
        "Заблокировать выделение, затем колесом задать число сегментов. Shift сглаживает "
        "кривую, Ctrl распределяет её точки, и каждый шаг прокрутки усиливает эффект. "
        "ЛКМ оставляет, ПКМ возвращает."
    ),
    (
        "*",
        "Quickly adjust the segment count of any edge:  scroll sets the count, Shift "
        "smooths the edge, Ctrl spreads the points evenly, and attributes such as "
        "UVs, seams and vertex colors survive the change intact.",
    ): (
        "Быстро меняет число сегментов любого ребра: колесо задаёт число, Shift "
        "сглаживает ребро, Ctrl распределяет его точки равномерно, а после "
        "регулировки такие атрибуты, как UV, швы и цвета вершин, сохраняются "
        "полностью."
    ),
    # The overlay's chip row.
    ("*", "[Wheel] Segments {entry} → {current}"): "[Колесо] Сегменты {entry} → {current}",
    ("*", "[Shift] Smooth"): "[Shift] Гладко",
    ("*", "[Ctrl] Even"): "[Ctrl] Ровно",
    ("*", "[LMB] Keep   [RMB] Revert"): "[ЛКМ] Оставить   [ПКМ] Вернуть",
    ("*", "Loop Resample failed safely: "): "Loop Resample безопасно прервано: ",
    # Reports.
    ("*", "Reverted to {counts} segment(s)."): "Возвращено сегментов: {counts}.",
    ("*", "Reverted to {counts} segment(s) and the original curve."): (
        "Возвращено сегментов: {counts}; исходная кривая тоже возвращена."
    ),
    ("*", "Left the curve as it was."): "Кривая оставлена без изменений.",
    ("*", "Kept {counts} segment(s) on the locked path(s)."): (
        "На заблокированных путях оставлено сегментов: {counts}."
    ),
    (
        "*",
        "Kept {counts} segment(s) and the adjusted curve on the locked path(s).",
    ): (
        "На заблокированных путях оставлено сегментов: {counts}; "
        "отрегулированная кривая тоже оставлена."
    ),
    (
        "*",
        "Resampled {paths} path(s): {changes}; rebuilt {strips} strip(s) with "
        "{faces} face(s)",
    ): (
        "Пересэмплировано путей: {paths} ({changes}); "
        "перестроено полос: {strips}, граней: {faces}"
    ),
    (
        "*",
        "No seam mark on {count} UV island boundary position(s), so one face there "
        "stretches across the UV map.  Mark Seam on those cuts to line them up.",
    ): (
        "На границах UV-островов есть места без отметки шва (всего {count}), поэтому одна "
        "грань там растягивается через всю UV-карту. Поставьте Mark Seam на этих разрезах, "
        "чтобы совместить их."
    ),
    # Refusals and failures, which reach the user as the warning chip.
    ("*", "closed"): "закрытый",
    ("*", "open"): "открытый",
    ("*", "A {kind} curve needs at least {minimum} points."): (
        "Кривая (тип: {kind}) требует не менее {minimum} точек."
    ),
    ("*", "A {kind} path needs at least {minimum} points."): (
        "Путь (тип: {kind}) требует не менее {minimum} точек."
    ),
    ("*", "A {kind} boundary needs at least {minimum} points."): (
        "Граница (тип: {kind}) требует не менее {minimum} точек."
    ),
    ("*", "A curve source contains a zero-length segment."): (
        "Источник кривой содержит сегмент нулевой длины."
    ),
    ("*", "A fitted curve segment has no measurable length."): (
        "Сегмент подогнанной кривой не имеет измеримой длины."
    ),
    ("*", "The fitted curve has no measurable length."): (
        "Подогнанная кривая не имеет измеримой длины."
    ),
    ("*", "A boundary contains a zero-length segment."): (
        "Граница содержит сегмент нулевой длины."
    ),
    ("*", "The strip plan contains no complete face sequence."): (
        "План полос не содержит полной последовательности граней."
    ),
    ("*", "The strip plan did not consume the full inner boundary."): (
        "План полос не использовал внутреннюю границу целиком."
    ),
    ("*", "The strip plan did not consume the full outer boundary."): (
        "План полос не использовал внешнюю границу целиком."
    ),
    ("*", "The strip plan contains a degenerate face."): (
        "План полос содержит вырожденную грань."
    ),
    ("*", "Select a continuous chain of edges or points."): (
        "Выберите непрерывную цепочку рёбер или точек."
    ),
    (
        "*",
        "The selected edges cross each other.  Keep only one direction of them.",
    ): "Выбранные рёбра пересекают друг друга. Оставьте только одно направление.",
    (
        "*",
        "The selected edges are not joined, so they cannot form one continuous chain.",
    ): "Выбранные рёбра не соединены, поэтому не могут образовать одну непрерывную цепочку.",
    (
        "*",
        "The selected edges are not continuous; there is a gap in between.",
    ): "Выбранные рёбра не непрерывны; между ними есть разрыв.",
    (
        "*",
        "The selected edges close back into a ring.  Break the loop and try again.",
    ): "Выбранные рёбра замыкаются в кольцо. Разорвите петлю и повторите.",
    ("*", "No valid ordered strip path was found."): (
        "Допустимый упорядоченный путь по полосам не найден."
    ),
    ("*", "The ordered strip contains intersecting edges."): (
        "Упорядоченные полосы содержат пересекающиеся рёбра."
    ),
    ("*", "The inner curve has too few points."): "У внутренней кривой слишком мало точек.",
    ("*", "The outer curve has too few points."): "У внешней кривой слишком мало точек.",
    (
        "*",
        "The faces beside this chain all close in on one point, so it has to be "
        "resampled as a whole ring.",
    ): (
        "Грани вдоль этой цепочки сходятся в одну точку, поэтому её нужно "
        "пересэмплировать целиком, как кольцо."
    ),
    (
        "*",
        "This chain of edges does not run between two matching strips of faces, so "
        "there is nothing here to resample.",
    ): (
        "Эта цепочка рёбер не проходит между двумя подходящими полосами граней, "
        "поэтому здесь нечего пересэмплировать."
    ),
    (
        "*",
        "The selected path contains a branch that cannot be resampled safely.",
    ): "Выбранный путь содержит ветвление, которое нельзя безопасно пересэмплировать.",
    ("*", "The target path would duplicate an existing edge."): (
        "Целевой путь продублирует существующее ребро."
    ),
    ("*", "The triangle-fan cap is no longer valid."): (
        "Крышка в виде треугольного веера больше не допустима."
    ),
    ("*", "An n-gon cap needs at least three boundary vertices."): (
        "Крышка n-gon требует не менее трёх вершин границы."
    ),
    ("*", "The n-gon cap boundary contains duplicate points."): (
        "Граница крышки n-gon содержит дублирующиеся точки."
    ),
    ("*", "The n-gon cap boundary is degenerate or self-intersecting."): (
        "Граница крышки n-gon вырождена или самопересекается."
    ),
    ("*", "The n-gon cap would contain a degenerate triangle."): (
        "Крышка n-gon будет содержать вырожденный треугольник."
    ),
    ("*", "The source no longer matches the locked selection."): (
        "Источник больше не совпадает с заблокированным выделением."
    ),
    ("*", "Select one path or multiple quad-connected parallel paths."): (
        "Выберите один путь или несколько параллельных путей, соединённых квадами."
    ),
    (
        "*",
        "Nothing here can be resampled.  Select a continuous chain of edges or points.",
    ): "Здесь нечего пересэмплировать. Выберите непрерывную цепочку рёбер или точек.",
    # Why the menu item is greyed out, and what a wheel that never started says.
    (
        "*",
        "Only available in mesh Edit Mode, with the vertex or edge select mode turned on.",
    ): (
        "Доступно только в режиме редактирования сетки, когда выбор установлен на вершины или рёбра."
    ),
    (
        "*",
        "The wheel could not start: this viewport no longer has a mesh to adjust.",
    ): (
        "Колесо не запустилось: в этом окне больше нет сетки для изменения."
    ),
}
