"""Traditional Chinese strings, keyed by the English sentence they replace.

This is the Traditional counterpart of zh_CN.py: the same entries in the same order, under
the same keys, with ``{counts}`` and friends staying exactly as they are while only the
words around them move.  The wording is Taiwan's Blender, not a converted copy of the
Simplified table.
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
        "鎖定目前的選取項，再用滾輪設定它的段數。按住 Shift 滾動可平滑曲線，"
        "按住 Ctrl 滾動可讓點的分布更均勻，每滾一格加強一檔。"
        "左鍵維持，右鍵回復之前的狀態"
    ),
    (
        "*",
        "Quickly adjust the segment count of any edge:  scroll sets the count, Shift "
        "smooths the edge, Ctrl spreads the points evenly, and attributes such as "
        "UVs, seams and vertex colors survive the change intact.",
    ): (
        "快速調節任意邊的段數，滾輪設定段數，Shift 平滑邊線，Ctrl 均勻分布，調節後 "
        "UV、接縫、頂點色等屬性完整保留。"
    ),
    # The overlay's chip row.
    ("*", "[Wheel] Segments {entry} → {current}"): "[滾輪] 段數 {entry} → {current}",
    ("*", "[Shift] Smooth"): "[Shift] 平滑",
    ("*", "[Ctrl] Even"): "[Ctrl] 均勻",
    ("*", "[LMB] Keep   [RMB] Revert"): "[左鍵] 維持   [右鍵] 回復",
    ("*", "Loop Resample failed safely: "): "Loop Resample 已安全失敗：",
    # Reports.
    ("*", "Reverted to {counts} segment(s)."): "已回復為 {counts} 段。",
    ("*", "Reverted to {counts} segment(s) and the original curve."): (
        "已回復為 {counts} 段並還原原始曲線。"
    ),
    ("*", "Kept {counts} segment(s) on the locked path(s)."): "已維持鎖定路徑的 {counts} 段。",
    (
        "*",
        "Kept {counts} segment(s) and the adjusted curve on the locked path(s).",
    ): "已維持鎖定路徑的 {counts} 段以及調整後的曲線。",
    (
        "*",
        "Resampled {paths} path(s): {changes}; rebuilt {strips} strip(s) with "
        "{faces} face(s)",
    ): "已重取樣 {paths} 條路徑：{changes}；重建 {strips} 個條帶，共 {faces} 個面",
    (
        "*",
        "No seam mark on {count} UV island boundary position(s), so one face there "
        "stretches across the UV map.  Mark Seam on those cuts to line them up.",
    ): (
        "{count} 處 UV 島的邊界上沒有縫線標記，那裡會有一個面被拉過整張 UV 映射。"
        "在這些切口上 Mark Seam 就能讓它們對齊。"
    ),
    # Refusals and failures, which reach the user as the warning chip.
    ("*", "closed"): "閉合",
    ("*", "open"): "開放",
    ("*", "A {kind} curve needs at least {minimum} points."): (
        "{kind}曲線至少需要 {minimum} 個點。"
    ),
    ("*", "A {kind} path needs at least {minimum} points."): (
        "{kind}路徑至少需要 {minimum} 個點。"
    ),
    ("*", "A {kind} boundary needs at least {minimum} points."): (
        "{kind}邊界至少需要 {minimum} 個點。"
    ),
    ("*", "A curve source contains a zero-length segment."): "曲線來源中包含長度為零的分段。",
    ("*", "A fitted curve segment has no measurable length."): "擬合曲線中有一段長度無法測量。",
    ("*", "The fitted curve has no measurable length."): "擬合曲線整體長度無法測量。",
    ("*", "A boundary contains a zero-length segment."): "邊界中包含長度為零的分段。",
    ("*", "The strip plan contains no complete face sequence."): (
        "條帶方案中沒有任何完整的面序列。"
    ),
    ("*", "The strip plan did not consume the full inner boundary."): (
        "條帶方案沒有用盡整條內邊界。"
    ),
    ("*", "The strip plan did not consume the full outer boundary."): (
        "條帶方案沒有用盡整條外邊界。"
    ),
    ("*", "The strip plan contains a degenerate face."): "條帶方案中包含退化面。",
    ("*", "Select a continuous chain of edges or points."): "請選取一條連續的邊或點。",
    (
        "*",
        "The selected edges cross each other.  Keep only one direction of them.",
    ): "選取的邊有交叉，請只選取一個方向。",
    (
        "*",
        "The selected edges are not joined, so they cannot form one continuous chain.",
    ): "選取的邊未相連，無法構成連續的邊。",
    (
        "*",
        "The selected edges are not continuous; there is a gap in between.",
    ): "選取的邊不連續，中間存在斷點。",
    (
        "*",
        "The selected edges close back into a ring.  Break the loop and try again.",
    ): "選取的邊已閉合成迴圈，請切斷迴路再試一次。",
    ("*", "No valid ordered strip path was found."): "未找到有效的有序條帶路徑。",
    ("*", "The ordered strip contains intersecting edges."): "有序條帶中包含相交的邊。",
    ("*", "The inner curve has too few points."): "內側曲線點數過少。",
    ("*", "The outer curve has too few points."): "外側曲線點數過少。",
    (
        "*",
        "The faces beside this chain all close in on one point, so it has to be "
        "resampled as a whole ring.",
    ): "這條邊旁邊的面全部收攏到同一個點上，所以要選取整圈才能重取樣。",
    (
        "*",
        "This chain of edges does not run between two matching strips of faces, so "
        "there is nothing here to resample.",
    ): "這條邊沒有位於兩組相對的面條帶之間，這裡沒有可重取樣的面。",
    (
        "*",
        "The selected path contains a branch that cannot be resampled safely.",
    ): "選取的路徑包含無法安全重取樣的分叉。",
    ("*", "The target path would duplicate an existing edge."): "目標路徑會重複現有的邊。",
    ("*", "The triangle-fan cap is no longer valid."): "三角扇蓋已失效。",
    ("*", "An n-gon cap needs at least three boundary vertices."): (
        "n-gon 蓋至少需要三個邊界頂點。"
    ),
    ("*", "The n-gon cap boundary contains duplicate points."): (
        "n-gon 蓋的邊界包含重複的點。"
    ),
    ("*", "The n-gon cap boundary is degenerate or self-intersecting."): (
        "n-gon 蓋的邊界退化或自交。"
    ),
    ("*", "The n-gon cap would contain a degenerate triangle."): "n-gon 蓋中會出現退化三角形。",
    ("*", "The source no longer matches the locked selection."): (
        "來源已與鎖定的選取項不一致。"
    ),
    (
        "*",
        "Select one path or multiple quad-connected parallel paths.",
    ): "請選取一條路徑，或多條以四邊形相連的並行路徑。",
    (
        "*",
        "Nothing here can be resampled.  Select a continuous chain of edges or points.",
    ): "這裡沒有可重取樣的東西。請選取一條連續的邊或點。",
}
