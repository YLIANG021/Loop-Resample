"""Portuguese strings, keyed by the English sentence they replace.

One table answers both pt-PT and pt-BR, spelled to the 1990 Orthographic Agreement
(``seleção``, ``selecionar``) so it reads the same in Lisbon and in São Paulo.
Placeholders travel with the sentence, so ``{counts}`` and friends stay exactly as they
are and only the words around them move.
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
        "Bloqueie a seleção e role a roda para definir o número de segmentos. Role com "
        "Shift para suavizar a curva, com Ctrl para distribuir os pontos, e cada passo da "
        "roda reforça esse efeito. O botão esquerdo mantém o resultado; o botão direito "
        "reverte."
    ),
    (
        "*",
        "Quickly adjust the segment count of any edge:  scroll sets the count, Shift "
        "smooths the edge, Ctrl spreads the points evenly, and attributes such as "
        "UVs, seams and vertex colors survive the change intact.",
    ): (
        "Ajusta rapidamente o número de segmentos de qualquer aresta: role a roda "
        "para definir a quantidade, use Shift para suavizar a aresta, Ctrl para "
        "distribuir os pontos, e atributos como UV, costuras e cores de vértice "
        "permanecem intactos após o ajuste."
    ),
    # The overlay's chip row.
    ("*", "[Wheel] Segments {entry} → {current}"): (
        "[Roda] Segmentos {entry} → {current}"
    ),
    ("*", "[Shift] Smooth"): "[Shift] Suavizar",
    ("*", "[Ctrl] Even"): "[Ctrl] Uniformizar",
    ("*", "[LMB] Keep   [RMB] Revert"): "[Bot. E] Manter   [Bot. D] Reverter",
    ("*", "Loop Resample failed safely: "): "Loop Resample falhou de forma segura: ",
    # Reports.
    ("*", "Reverted to {counts} segment(s)."): "Revertido para {counts} segmento(s).",
    ("*", "Reverted to {counts} segment(s) and the original curve."): (
        "Revertido para {counts} segmento(s) e para a curva original."
    ),
    ("*", "Left the curve as it was."): "A curva ficou como estava.",
    ("*", "Kept {counts} segment(s) on the locked path(s)."): (
        "Mantidos {counts} segmento(s) nos caminhos bloqueados."
    ),
    (
        "*",
        "Kept {counts} segment(s) and the adjusted curve on the locked path(s).",
    ): "Mantidos {counts} segmento(s) e a curva ajustada nos caminhos bloqueados.",
    (
        "*",
        "Resampled {paths} path(s): {changes}; rebuilt {strips} strip(s) with "
        "{faces} face(s)",
    ): (
        "Reamostrados {paths} caminho(s): {changes}; reconstruídas {strips} faixa(s) "
        "com {faces} face(s)"
    ),
    (
        "*",
        "No seam mark on {count} UV island boundary position(s), so one face there "
        "stretches across the UV map.  Mark Seam on those cuts to line them up.",
    ): (
        "Não há marca de costura em {count} posição(ões) do limite de uma ilha UV; por "
        "isso, nesse local uma face estende-se por todo o mapa UV. Use Mark Seam "
        "nesses cortes para alinhá-los."
    ),
    # Refusals and failures, which reach the user as the warning chip.
    ("*", "closed"): "fechado",
    ("*", "open"): "aberto",
    ("*", "A {kind} curve needs at least {minimum} points."): (
        "Uma curva (tipo {kind}) precisa de pelo menos {minimum} pontos."
    ),
    ("*", "A {kind} path needs at least {minimum} points."): (
        "Um caminho (tipo {kind}) precisa de pelo menos {minimum} pontos."
    ),
    ("*", "A {kind} boundary needs at least {minimum} points."): (
        "Um limite (tipo {kind}) precisa de pelo menos {minimum} pontos."
    ),
    ("*", "A curve source contains a zero-length segment."): (
        "Uma fonte de curva contém um segmento de comprimento zero."
    ),
    ("*", "A fitted curve segment has no measurable length."): (
        "Um segmento da curva ajustada não tem comprimento mensurável."
    ),
    ("*", "The fitted curve has no measurable length."): (
        "A curva ajustada não tem comprimento mensurável."
    ),
    ("*", "A boundary contains a zero-length segment."): (
        "Um limite contém um segmento de comprimento zero."
    ),
    ("*", "The strip plan contains no complete face sequence."): (
        "O plano de faixa não contém nenhuma sequência completa de faces."
    ),
    ("*", "The strip plan did not consume the full inner boundary."): (
        "O plano de faixa não consumiu todo o limite interno."
    ),
    ("*", "The strip plan did not consume the full outer boundary."): (
        "O plano de faixa não consumiu todo o limite externo."
    ),
    ("*", "The strip plan contains a degenerate face."): (
        "O plano de faixa contém uma face degenerada."
    ),
    ("*", "Select a continuous chain of edges or points."): (
        "Selecione uma cadeia contínua de arestas ou pontos."
    ),
    (
        "*",
        "The selected edges cross each other.  Keep only one direction of them.",
    ): "As arestas selecionadas cruzam-se. Mantenha apenas uma das direções.",
    (
        "*",
        "The selected edges are not joined, so they cannot form one continuous chain.",
    ): (
        "As arestas selecionadas não estão ligadas, portanto não podem formar uma "
        "única cadeia contínua."
    ),
    (
        "*",
        "The selected edges are not continuous; there is a gap in between.",
    ): "As arestas selecionadas não são contínuas; há um vão entre elas.",
    (
        "*",
        "The selected edges close back into a ring.  Break the loop and try again.",
    ): "As arestas selecionadas fecham-se num anel. Quebre o laço e tente novamente.",
    ("*", "No valid ordered strip path was found."): (
        "Não foi encontrado nenhum caminho válido de faixa ordenada."
    ),
    ("*", "The ordered strip contains intersecting edges."): (
        "A faixa ordenada contém arestas que se intersectam."
    ),
    ("*", "The inner curve has too few points."): "A curva interna tem poucos pontos.",
    ("*", "The outer curve has too few points."): "A curva externa tem poucos pontos.",
    (
        "*",
        "The faces beside this chain all close in on one point, so it has to be "
        "resampled as a whole ring.",
    ): (
        "Todas as faces ao lado desta cadeia convergem para um único ponto, por isso "
        "é preciso reamostrá-la como um anel completo."
    ),
    (
        "*",
        "This chain of edges does not run between two matching strips of faces, so "
        "there is nothing here to resample.",
    ): (
        "Esta cadeia de arestas não passa entre duas faixas de faces compatíveis, por "
        "isso não há nada aqui para reamostrar."
    ),
    (
        "*",
        "The selected path contains a branch that cannot be resampled safely.",
    ): (
        "O caminho selecionado contém uma ramificação que não pode ser reamostrada "
        "com segurança."
    ),
    ("*", "The target path would duplicate an existing edge."): (
        "O caminho-alvo duplicaria uma aresta existente."
    ),
    ("*", "The triangle-fan cap is no longer valid."): (
        "A tampa em leque de triângulos já não é válida."
    ),
    ("*", "An n-gon cap needs at least three boundary vertices."): (
        "Uma tampa n-gon precisa de pelo menos três vértices do limite."
    ),
    ("*", "The n-gon cap boundary contains duplicate points."): (
        "O limite da tampa n-gon contém pontos duplicados."
    ),
    ("*", "The n-gon cap boundary is degenerate or self-intersecting."): (
        "O limite da tampa n-gon é degenerado ou auto-intersectante."
    ),
    ("*", "The n-gon cap would contain a degenerate triangle."): (
        "A tampa n-gon conteria um triângulo degenerado."
    ),
    ("*", "The source no longer matches the locked selection."): (
        "A fonte já não corresponde à seleção bloqueada."
    ),
    (
        "*",
        "Select one path or multiple quad-connected parallel paths.",
    ): "Selecione um caminho ou vários caminhos paralelos ligados por quadriláteros.",
    (
        "*",
        "Nothing here can be resampled.  Select a continuous chain of edges or points.",
    ): "Nada aqui pode ser reamostrado. Selecione uma cadeia contínua de arestas ou pontos.",
}
