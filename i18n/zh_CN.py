"""Simplified Chinese strings, keyed by the English sentence they replace.

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
        "锁定当前选择，滚轮设置段数。按住 Shift 滚动可平滑曲线，"
        "按住 Ctrl 滚动可让点分布更均匀，每滚一格加强一档。左键保留，右键还原之前的状态"
    ),
    ("*", "Enter Loop Resample"): "进入环带重采样",
    ("*", "Lock the current mesh and selection as the resample source"): "把当前网格与选择锁定为重采样源",
    ("*", "Loop Resample"): "环带重采样",
    ("*", "Resample the locked paths from the session source"): "从会话源重采样已锁定的路径",
    ("*", "Confirm Resample"): "确认重采样",
    ("*", "Keep the current result and end the session"): "保留当前结果并结束会话",
    ("*", "Cancel Resample"): "取消重采样",
    ("*", "Restore the mesh to its state when the session started"): "把网格恢复到会话开始时的状态",
    # The overlay's chip row.
    ("*", "[Wheel] Segments {entry} → {current}"): "[滚轮] 段数 {entry} → {current}",
    ("*", "[Shift] Smooth"): "[Shift] 平滑",
    ("*", "[Ctrl] Even"): "[Ctrl] 均分",
    ("*", "[LMB] Keep   [RMB] Revert"): "[左键] 保留   [右键] 还原",
    ("*", "Loop Resample failed safely: "): "环带重采样已安全失败：",
    # Reports.
    ("*", "Locked {count} path(s): {counts}"): "已锁定 {count} 条路径：{counts}",
    ("*", "Mesh update is already running; wait a moment."): "网格更新正在进行，请稍候。",
    ("*", "Enter adjust mode first."): "请先进入调整模式。",
    ("*", "Restored the mesh from before the session."): "已恢复会话开始前的网格。",
    ("*", "Reverted to {counts} segment(s)."): "已还原为 {counts} 段。",
    ("*", "Reverted to {counts} segment(s) and the original curve."): "已还原为 {counts} 段并恢复原始曲线。",
    ("*", "Kept {counts} segment(s) on the locked path(s)."): "已保留锁定路径的 {counts} 段。",
    (
        "*",
        "Kept {counts} segment(s) and the adjusted curve on the locked path(s).",
    ): "已保留锁定路径的 {counts} 段以及调整后的曲线。",
    (
        "*",
        "Resampled {paths} path(s): {changes}; rebuilt {strips} strip(s) with "
        "{faces} face(s)",
    ): "已重采样 {paths} 条路径：{changes}；重建 {strips} 条条带，共 {faces} 个面",
    (
        "*",
        "No seam mark on {count} UV island boundary position(s), so one face there "
        "stretches across the UV map.  Mark Seam on those cuts to line them up.",
    ): (
        "{count} 处 UV 岛的边界上没有缝标记，那里会有一张面被拉过整张 UV 图。"
        "把这些切口 Mark Seam 就能对齐。"
    ),
    # Refusals and failures, which reach the user as the warning chip.
    ("*", "closed"): "闭合",
    ("*", "open"): "开放",
    ("*", "A {kind} curve needs at least {minimum} points."): "{kind}曲线至少需要 {minimum} 个点。",
    ("*", "A {kind} path needs at least {minimum} points."): "{kind}路径至少需要 {minimum} 个点。",
    ("*", "A {kind} boundary needs at least {minimum} points."): "{kind}边界至少需要 {minimum} 个点。",
    ("*", "A curve source contains a zero-length segment."): "曲线源中包含零长度的段。",
    ("*", "A fitted curve segment has no measurable length."): "拟合曲线中有一段长度无法测量。",
    ("*", "The fitted curve has no measurable length."): "拟合曲线整体长度无法测量。",
    ("*", "A boundary contains a zero-length segment."): "边界中包含零长度的段。",
    ("*", "The strip plan contains no complete face sequence."): "条带方案中没有任何完整的面序列。",
    ("*", "The strip plan did not consume the full inner boundary."): "条带方案没有用尽整条内边界。",
    ("*", "The strip plan did not consume the full outer boundary."): "条带方案没有用尽整条外边界。",
    ("*", "The strip plan contains a degenerate face."): "条带方案中包含退化面。",
    ("*", "Select a continuous chain of edges or points."): "请选择一条连续的边或者点。",
    (
        "*",
        "The selected edges cross each other.  Keep only one direction of them.",
    ): "选中的边有交叉，请只选一个方向。",
    (
        "*",
        "The selected edges are not joined, so they cannot form one continuous chain.",
    ): "选择的边未相连，无法构成连续边。",
    (
        "*",
        "The selected edges are not continuous; there is a gap in between.",
    ): "选中的边不连续，中间存在断点。",
    (
        "*",
        "The selected edges close back into a ring.  Break the loop and try again.",
    ): "选中边已连成圈，请取消闭环。",
    ("*", "No valid ordered strip path was found."): "未找到有效的有序条带路径。",
    ("*", "The ordered strip contains intersecting edges."): "有序条带中包含相交的边。",
    ("*", "The inner curve has too few points."): "内侧曲线点数过少。",
    ("*", "The outer curve has too few points."): "外侧曲线点数过少。",
    (
        "*",
        "The faces beside this chain all close in on one point, so it has to be "
        "resampled as a whole ring.",
    ): "这条边旁边的面全部收拢到同一个点上，所以要选整圈才能重采样。",
    (
        "*",
        "This chain of edges does not run between two matching strips of faces, so "
        "there is nothing here to resample.",
    ): "边的位置不正确，缺少可重采样的面。",
    (
        "*",
        "The selected path contains a branch that cannot be resampled safely.",
    ): "所选路径包含无法重采样的分叉。",
    ("*", "The target path would duplicate an existing edge."): "目标路径会重复已有的边。",
    ("*", "The triangle-fan cap is no longer valid."): "三角扇盖已失效。",
    ("*", "An n-gon cap needs at least three boundary vertices."): "n 边形盖至少需要三个边界顶点。",
    ("*", "The n-gon cap boundary contains duplicate points."): "n 边形盖的边界包含重复点。",
    ("*", "The n-gon cap boundary is degenerate or self-intersecting."): "n 边形盖的边界退化或自交。",
    ("*", "The n-gon cap would contain a degenerate triangle."): "n 边形盖中会出现退化三角形。",
    ("*", "The source no longer matches the locked selection."): "源网格已与锁定的选择不一致。",
    (
        "*",
        "Select one path or multiple quad-connected parallel paths.",
    ): "请选择一条路径，或多条以四边形相连的并行路径。",
    (
        "*",
        "Nothing here can be resampled.  Select a continuous chain of edges or points.",
    ): "这里没有可重采样的东西。请选一条连续的边或者点。",
}
