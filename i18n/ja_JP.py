"""Japanese strings, keyed by the English sentence they replace.

The wording follows Blender's own Japanese UI terms, and the placeholders travel with the
sentence, so ``{counts}`` and friends stay exactly as they are.
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
        "選択をロックしてからホイールを回すと、セグメント数を設定できます。Shift キーで"
        "カーブがスムーズになり、Ctrl キーでポイントが均一に並びます。1 目盛ごとに"
        "効果が強まります。左クリックで維持、右クリックで元に戻す。"
    ),
    ("*", "Enter Loop Resample"): "ループリサンプルに入る",
    (
        "*",
        "Lock the current mesh and selection as the resample source",
    ): "現在のメッシュと選択をリサンプルのソースとしてロックします",
    ("*", "Loop Resample"): "ループリサンプル",
    (
        "*",
        "Resample the locked paths from the session source",
    ): "セッションのソースからロックしたパスをリサンプルします",
    ("*", "Confirm Resample"): "リサンプルを確認",
    ("*", "Keep the current result and end the session"): "現在の結果を維持してセッションを終了します",
    ("*", "Cancel Resample"): "リサンプルをキャンセル",
    ("*", "Restore the mesh to its state when the session started"): "メッシュをセッション開始時の状態に戻します",
    # The overlay's chip row.
    ("*", "[Wheel] Segments {entry} → {current}"): "[ホイール] セグ数 {entry} → {current}",
    ("*", "[Shift] Smooth"): "[Shift] スムーズ",
    ("*", "[Ctrl] Even"): "[Ctrl] 均一",
    ("*", "[LMB] Keep   [RMB] Revert"): "[左] 維持   [右] 元に戻す",
    ("*", "Loop Resample failed safely: "): "ループリサンプルは安全に失敗しました： ",
    # Reports.
    ("*", "Locked {count} path(s): {counts}"): "{count} 本のパスをロックしました：{counts}",
    (
        "*",
        "Mesh update is already running; wait a moment.",
    ): "メッシュの更新が既に実行中です。しばらくお待ちください。",
    ("*", "Enter adjust mode first."): "先に調整モードに入ってください。",
    ("*", "Restored the mesh from before the session."): "セッション開始前のメッシュに戻しました。",
    ("*", "Reverted to {counts} segment(s)."): "{counts} セグメントに戻しました。",
    (
        "*",
        "Reverted to {counts} segment(s) and the original curve.",
    ): "{counts} セグメントと元のカーブに戻しました。",
    (
        "*",
        "Kept {counts} segment(s) on the locked path(s).",
    ): "ロックしたパスの {counts} セグメントを維持しました。",
    (
        "*",
        "Kept {counts} segment(s) and the adjusted curve on the locked path(s).",
    ): "ロックしたパスの {counts} セグメントと調整後のカーブを維持しました。",
    (
        "*",
        "Resampled {paths} path(s): {changes}; rebuilt {strips} strip(s) with "
        "{faces} face(s)",
    ): (
        "{paths} 本のパスをリサンプルしました：{changes}。"
        "{strips} 本のストリップを {faces} 面で再構築しました。"
    ),
    (
        "*",
        "No seam mark on {count} UV island boundary position(s), so one face there "
        "stretches across the UV map.  Mark Seam on those cuts to line them up.",
    ): (
        "{count} 箇所の UV アイランドの境界にシームのマークがないため、そこでは "
        "1 つの面が UV マップいっぱいに伸びます。その切れ目に Mark Seam を適用すると"
        "揃います。"
    ),
    # Refusals and failures, which reach the user as the warning chip.
    ("*", "closed"): "閉じた",
    ("*", "open"): "開いた",
    (
        "*",
        "A {kind} curve needs at least {minimum} points.",
    ): "{kind}カーブには少なくとも {minimum} 個のポイントが必要です。",
    (
        "*",
        "A {kind} path needs at least {minimum} points.",
    ): "{kind}パスには少なくとも {minimum} 個のポイントが必要です。",
    (
        "*",
        "A {kind} boundary needs at least {minimum} points.",
    ): "{kind}境界には少なくとも {minimum} 個のポイントが必要です。",
    (
        "*",
        "A curve source contains a zero-length segment.",
    ): "カーブのソースに長さがゼロのセグメントが含まれています。",
    (
        "*",
        "A fitted curve segment has no measurable length.",
    ): "フィットさせたカーブのセグメントの長さを測定できません。",
    (
        "*",
        "The fitted curve has no measurable length.",
    ): "フィットさせたカーブ全体の長さを測定できません。",
    (
        "*",
        "A boundary contains a zero-length segment.",
    ): "境界に長さがゼロのセグメントが含まれています。",
    (
        "*",
        "The strip plan contains no complete face sequence.",
    ): "ストリップの計画に完全な面シーケンスがありません。",
    (
        "*",
        "The strip plan did not consume the full inner boundary.",
    ): "ストリップの計画が内側の境界全体を覆っていません。",
    (
        "*",
        "The strip plan did not consume the full outer boundary.",
    ): "ストリップの計画が外側の境界全体を覆っていません。",
    (
        "*",
        "The strip plan contains a degenerate face.",
    ): "ストリップの計画に退化した面が含まれています。",
    (
        "*",
        "Select a continuous chain of edges or points.",
    ): "連続した辺またはポイントのチェーンを選択してください。",
    (
        "*",
        "The selected edges cross each other.  Keep only one direction of them.",
    ): "選択した辺が互いに交差しています。片方の方向だけを維持してください。",
    (
        "*",
        "The selected edges are not joined, so they cannot form one continuous chain.",
    ): "選択した辺が接続されていないため、1 つの連続したチェーンを形成できません。",
    (
        "*",
        "The selected edges are not continuous; there is a gap in between.",
    ): "選択した辺が連続していません。間に隙間があります。",
    (
        "*",
        "The selected edges close back into a ring.  Break the loop and try again.",
    ): "選択した辺が閉じた輪になっています。ループを解除して再度お試しください。",
    ("*", "No valid ordered strip path was found."): "有効な順序付きストリップパスが見つかりませんでした。",
    (
        "*",
        "The ordered strip contains intersecting edges.",
    ): "順序付きストリップに交差する辺が含まれています。",
    (
        "*",
        "The inner curve has too few points.",
    ): "内側のカーブのポイントが少なすぎます。",
    (
        "*",
        "The outer curve has too few points.",
    ): "外側のカーブのポイントが少なすぎます。",
    (
        "*",
        "The faces beside this chain all close in on one point, so it has to be "
        "resampled as a whole ring.",
    ): (
        "このチェーンの隣の面はすべて 1 つのポイントに収束しているため、"
        "輪全体としてリサンプルする必要があります。"
    ),
    (
        "*",
        "This chain of edges does not run between two matching strips of faces, so "
        "there is nothing here to resample.",
    ): (
        "この辺のチェーンは対応する 2 つの面のストリップの間に通っていないため、"
        "リサンプルできるものはありません。"
    ),
    (
        "*",
        "The selected path contains a branch that cannot be resampled safely.",
    ): "選択したパスに安全にリサンプルできない分岐が含まれています。",
    (
        "*",
        "The target path would duplicate an existing edge.",
    ): "ターゲットのパスは既存の辺を複製することになります。",
    (
        "*",
        "The triangle-fan cap is no longer valid.",
    ): "三角ファンのキャップは有効ではなくなりました。",
    (
        "*",
        "An n-gon cap needs at least three boundary vertices.",
    ): "n-gon キャップには少なくとも 3 個の境界頂点が必要です。",
    (
        "*",
        "The n-gon cap boundary contains duplicate points.",
    ): "n-gon キャップの境界に重複したポイントが含まれています。",
    (
        "*",
        "The n-gon cap boundary is degenerate or self-intersecting.",
    ): "n-gon キャップの境界が退化しているか自己交差しています。",
    (
        "*",
        "The n-gon cap would contain a degenerate triangle.",
    ): "n-gon キャップに退化した三角形ができます。",
    (
        "*",
        "The source no longer matches the locked selection.",
    ): "ソースがロックした選択と一致しなくなりました。",
    (
        "*",
        "Select one path or multiple quad-connected parallel paths.",
    ): "1 本のパス、または四角面でつながった複数の平行なパスを選択してください。",
    (
        "*",
        "Nothing here can be resampled.  Select a continuous chain of edges or points.",
    ): (
        "ここにはリサンプルできるものはありません。"
        "連続した辺またはポイントのチェーンを選択してください。"
    ),
}
