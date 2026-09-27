"""Korean strings, keyed by the English sentence they replace.

The keys are copied byte-for-byte from the English source, so only the Korean values move;
``{counts}`` and friends travel with their sentence exactly as they are.
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
        "선택을 잠근 뒤 휠을 굴려 세그먼트 수를 설정하십시오. Shift를 누른 채로 굴리면 커브가 "
        "스무스해지고, Ctrl를 누른 채로 굴리면 포인트 배분이 균일해지며, 한 칸씩 효과가 "
        "강해집니다. 좌클릭은 유지, 우클릭은 되돌립니다."
    ),
    ("*", "Enter Loop Resample"): "루프 재샘플링 진입",
    ("*", "Lock the current mesh and selection as the resample source"): (
        "현재 메시와 선택을 재샘플링 소스로 잠금"
    ),
    ("*", "Loop Resample"): "루프 재샘플링",
    ("*", "Resample the locked paths from the session source"): "세션 소스에서 잠긴 경로를 재샘플링",
    ("*", "Confirm Resample"): "재샘플링 확인",
    ("*", "Keep the current result and end the session"): "현재 결과를 유지하고 세션 종료",
    ("*", "Cancel Resample"): "재샘플링 취소",
    ("*", "Restore the mesh to its state when the session started"): (
        "세션 시작 시점의 메시로 복원"
    ),
    # The overlay's chip row.
    ("*", "[Wheel] Segments {entry} → {current}"): "[휠] 세그먼트 {entry} → {current}",
    ("*", "[Shift] Smooth"): "[Shift] 스무스",
    ("*", "[Ctrl] Even"): "[Ctrl] 균일",
    ("*", "[LMB] Keep   [RMB] Revert"): "[좌클릭] 유지   [우클릭] 되돌리기",
    ("*", "Loop Resample failed safely: "): "루프 재샘플링이 안전하게 실패했습니다: ",
    # Reports.
    ("*", "Locked {count} path(s): {counts}"): "경로 {count}개를 잠갔습니다: {counts}",
    ("*", "Mesh update is already running; wait a moment."): (
        "이미 메시 업데이트가 진행 중입니다. 잠시 기다리십시오."
    ),
    ("*", "Enter adjust mode first."): "먼저 조정 모드에 진입하십시오.",
    ("*", "Restored the mesh from before the session."): "세션 시작 전의 메시로 복원되었습니다.",
    ("*", "Reverted to {counts} segment(s)."): "{counts}개 세그먼트로 되돌렸습니다.",
    ("*", "Reverted to {counts} segment(s) and the original curve."): (
        "{counts}개 세그먼트와 원본 커브로 되돌렸습니다."
    ),
    ("*", "Kept {counts} segment(s) on the locked path(s)."): (
        "잠긴 경로에 {counts}개 세그먼트를 유지했습니다."
    ),
    (
        "*",
        "Kept {counts} segment(s) and the adjusted curve on the locked path(s).",
    ): "잠긴 경로에 {counts}개 세그먼트와 조정된 커브를 유지했습니다.",
    (
        "*",
        "Resampled {paths} path(s): {changes}; rebuilt {strips} strip(s) with "
        "{faces} face(s)",
    ): "경로 {paths}개를 재샘플링했습니다: {changes}; 스트립 {strips}개 재구축, 페이스 {faces}개",
    (
        "*",
        "No seam mark on {count} UV island boundary position(s), so one face there "
        "stretches across the UV map.  Mark Seam on those cuts to line them up.",
    ): (
        "{count}개의 UV 아일랜드 경계 위치에 심이 마킹되지 않아 그 위치의 페이스 하나가 "
        "UV 맵을 가로질러 늘어납니다. 해당 절단선에 Mark Seam을 실행해 정렬하십시오."
    ),
    # Refusals and failures, which reach the user as the warning chip.
    ("*", "closed"): "닫힌",
    ("*", "open"): "열린",
    ("*", "A {kind} curve needs at least {minimum} points."): (
        "{kind} 커브에는 최소 {minimum}개의 포인트가 필요합니다."
    ),
    ("*", "A {kind} path needs at least {minimum} points."): (
        "{kind} 경로에는 최소 {minimum}개의 포인트가 필요합니다."
    ),
    ("*", "A {kind} boundary needs at least {minimum} points."): (
        "{kind} 경계에는 최소 {minimum}개의 포인트가 필요합니다."
    ),
    ("*", "A curve source contains a zero-length segment."): (
        "커브 소스에 길이가 0인 세그먼트가 있습니다."
    ),
    ("*", "A fitted curve segment has no measurable length."): (
        "피팅된 커브 세그먼트의 길이를 측정할 수 없습니다."
    ),
    ("*", "The fitted curve has no measurable length."): "피팅된 커브의 길이를 측정할 수 없습니다.",
    ("*", "A boundary contains a zero-length segment."): "경계에 길이가 0인 세그먼트가 있습니다.",
    ("*", "The target count cannot preserve every feature anchor."): (
        "대상 수로 모든 특성 앵커를 유지할 수 없습니다."
    ),
    ("*", "Feature anchors do not span a valid boundary."): (
        "특성 앵커가 유효한 경계를 만들지 않습니다."
    ),
    (
        "*",
        "Feature-aware sampling returned the wrong point count.",
    ): "특성 인지 샘플링이 잘못된 포인트 수를 반환했습니다.",
    ("*", "The strip plan contains no complete face sequence."): (
        "스트립 계획에 완전한 페이스 시퀀스가 없습니다."
    ),
    ("*", "The strip plan did not consume the full inner boundary."): (
        "스트립 계획이 안쪽 경계를 모두 소모하지 않았습니다."
    ),
    ("*", "The strip plan did not consume the full outer boundary."): (
        "스트립 계획이 바깥 경계를 모두 소모하지 않았습니다."
    ),
    ("*", "The strip plan contains a degenerate face."): "스트립 계획에 퇴화된 페이스가 있습니다.",
    ("*", "Select a continuous chain of edges or points."): (
        "엣지 또는 포인트의 연속된 체인을 선택하십시오."
    ),
    (
        "*",
        "The selected edges cross each other.  Keep only one direction of them.",
    ): "선택한 엣지가 서로 교차합니다. 한 방향만 유지하십시오.",
    (
        "*",
        "The selected edges are not joined, so they cannot form one continuous chain.",
    ): "선택한 엣지가 연결되지 않아 하나의 연속된 체인을 만들 수 없습니다.",
    (
        "*",
        "The selected edges are not continuous; there is a gap in between.",
    ): "선택한 엣지가 연속되지 않았습니다. 사이에 틈이 있습니다.",
    (
        "*",
        "The selected edges close back into a ring.  Break the loop and try again.",
    ): "선택한 엣지가 링으로 다시 닫혔습니다. 루프를 끊고 다시 시도하십시오.",
    ("*", "No valid ordered strip path was found."): (
        "순서가 맞는 유효한 스트립 경로를 찾을 수 없습니다."
    ),
    ("*", "The ordered strip contains intersecting edges."): (
        "순서가 맞는 스트립에 교차하는 엣지가 있습니다."
    ),
    ("*", "The inner curve has too few points."): "안쪽 커브의 포인트가 너무 적습니다.",
    ("*", "The outer curve has too few points."): "바깥 커브의 포인트가 너무 적습니다.",
    (
        "*",
        "The faces beside this chain all close in on one point, so it has to be "
        "resampled as a whole ring.",
    ): (
        "이 체인 옆의 페이스가 모두 한 포인트로 닫혀 들어가므로 전체 링으로 "
        "재샘플링해야 합니다."
    ),
    (
        "*",
        "This chain of edges does not run between two matching strips of faces, so "
        "there is nothing here to resample.",
    ): (
        "이 엣지 체인이 서로 맞는 두 페이스 스트립 사이를 지나지 않아 여기에는 "
        "재샘플링할 것이 없습니다."
    ),
    (
        "*",
        "The selected path contains a branch that cannot be resampled safely.",
    ): "선택한 경로에 안전하게 재샘플링할 수 없는 분기가 있습니다.",
    ("*", "The target path would duplicate an existing edge."): (
        "대상 경로가 이미 있는 엣지를 복제합니다."
    ),
    ("*", "The triangle-fan cap is no longer valid."): "삼각형 부채꼴 캡이 더 이상 유효하지 않습니다.",
    ("*", "An n-gon cap needs at least three boundary vertices."): (
        "n-gon 캡에는 최소 3개의 경계 버텍스가 필요합니다."
    ),
    ("*", "The n-gon cap boundary contains duplicate points."): (
        "n-gon 캡 경계에 중복된 포인트가 있습니다."
    ),
    (
        "*",
        "The n-gon cap boundary is degenerate or self-intersecting.",
    ): "n-gon 캡 경계가 퇴화되었거나 스스로 교차합니다.",
    ("*", "The n-gon cap would contain a degenerate triangle."): (
        "n-gon 캡에 퇴화된 삼각형이 생깁니다."
    ),
    ("*", "The source no longer matches the locked selection."): (
        "소스가 잠긴 선택과 더 이상 일치하지 않습니다."
    ),
    (
        "*",
        "Select one path or multiple quad-connected parallel paths.",
    ): "하나의 경로 또는 쿼드로 연결된 여러 평행 경로를 선택하십시오.",
    (
        "*",
        "Nothing here can be resampled.  Select a continuous chain of edges or points.",
    ): (
        "여기에는 재샘플링할 것이 없습니다. 엣지 또는 포인트의 연속된 체인을 선택하십시오."
    ),
}
