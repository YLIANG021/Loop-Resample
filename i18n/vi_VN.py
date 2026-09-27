"""Vietnamese (vi_VN) strings, keyed by the English sentence they replace.

The English sentence stays the key, so a string that has not caught up simply answers with
the English source.  Placeholders travel with the sentence, so ``{counts}`` and friends stay
exactly as they are and only the words around them move.
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
        "Khóa lựa chọn, rồi lăn bánh xe để đặt số đoạn của nó. Giữ Shift và lăn để làm mịn "
        "đường cong, giữ Ctrl và lăn để chia đều các điểm, mỗi nấc lăn tăng thêm một bậc "
        "cho hiệu ứng đó. Chuột trái giữ kết quả, chuột phải hoàn tác."
    ),
    ("*", "Enter Loop Resample"): "Vào chế độ lấy mẫu lại vòng lặp",
    (
        "*",
        "Lock the current mesh and selection as the resample source",
    ): "Khóa mesh và lựa chọn hiện tại làm nguồn lấy mẫu lại",
    ("*", "Loop Resample"): "Lấy mẫu lại vòng lặp",
    (
        "*",
        "Resample the locked paths from the session source",
    ): "Lấy mẫu lại các đường dẫn đã khóa từ nguồn của phiên",
    ("*", "Confirm Resample"): "Xác nhận lấy mẫu lại",
    (
        "*",
        "Keep the current result and end the session",
    ): "Giữ kết quả hiện tại và kết thúc phiên",
    ("*", "Cancel Resample"): "Hủy lấy mẫu lại",
    (
        "*",
        "Restore the mesh to its state when the session started",
    ): "Đưa mesh về trạng thái lúc bắt đầu phiên",
    # The overlay's chip row.
    ("*", "[Wheel] Segments {entry} → {current}"): "[Lăn] Số đoạn {entry} → {current}",
    ("*", "[Shift] Smooth"): "[Shift] Làm mịn",
    ("*", "[Ctrl] Even"): "[Ctrl] Chia đều",
    ("*", "[LMB] Keep   [RMB] Revert"): "[Trái] Giữ   [Phải] Hoàn tác",
    ("*", "Loop Resample failed safely: "): "Lấy mẫu lại vòng lặp thất bại an toàn: ",
    # Reports.
    ("*", "Locked {count} path(s): {counts}"): "Đã khóa {count} đường dẫn: {counts}",
    (
        "*",
        "Mesh update is already running; wait a moment.",
    ): "Đang cập nhật mesh, hãy chờ một lát.",
    ("*", "Enter adjust mode first."): "Hãy vào chế độ điều chỉnh trước.",
    ("*", "Restored the mesh from before the session."): "Đã khôi phục mesh như trước phiên.",
    ("*", "Reverted to {counts} segment(s)."): "Đã hoàn tác về {counts} đoạn.",
    (
        "*",
        "Reverted to {counts} segment(s) and the original curve.",
    ): "Đã hoàn tác về {counts} đoạn và đường cong gốc.",
    (
        "*",
        "Kept {counts} segment(s) on the locked path(s).",
    ): "Đã giữ {counts} đoạn trên các đường dẫn đã khóa.",
    (
        "*",
        "Kept {counts} segment(s) and the adjusted curve on the locked path(s).",
    ): "Đã giữ {counts} đoạn và đường cong đã điều chỉnh trên các đường dẫn đã khóa.",
    (
        "*",
        "Resampled {paths} path(s): {changes}; rebuilt {strips} strip(s) with "
        "{faces} face(s)",
    ): "Đã lấy mẫu lại {paths} đường dẫn: {changes}; dựng lại {strips} dải với {faces} mặt",
    (
        "*",
        "No seam mark on {count} UV island boundary position(s), so one face there "
        "stretches across the UV map.  Mark Seam on those cuts to line them up.",
    ): (
        "Không có dấu đường khâu ở {count} vị trí ranh giới đảo UV, nên một mặt tại đó bị "
        "kéo dài khắp ánh xạ UV. Hãy đánh dấu Mark Seam trên các vết cắt đó để thẳng hàng."
    ),
    # Refusals and failures, which reach the user as the warning chip.
    ("*", "closed"): "kín",
    ("*", "open"): "mở",
    (
        "*",
        "A {kind} curve needs at least {minimum} points.",
    ): "Đường cong {kind} cần tối thiểu {minimum} điểm.",
    (
        "*",
        "A {kind} path needs at least {minimum} points.",
    ): "Đường dẫn {kind} cần tối thiểu {minimum} điểm.",
    (
        "*",
        "A {kind} boundary needs at least {minimum} points.",
    ): "Ranh giới {kind} cần tối thiểu {minimum} điểm.",
    (
        "*",
        "A curve source contains a zero-length segment.",
    ): "Nguồn đường cong có một đoạn dài bằng không.",
    (
        "*",
        "A fitted curve segment has no measurable length.",
    ): "Một đoạn của đường cong khớp không có chiều dài đo được.",
    (
        "*",
        "The fitted curve has no measurable length.",
    ): "Đường cong khớp không có chiều dài đo được.",
    (
        "*",
        "A boundary contains a zero-length segment.",
    ): "Ranh giới có một đoạn dài bằng không.",
    (
        "*",
        "The target count cannot preserve every feature anchor.",
    ): "Số mục tiêu không giữ được mọi điểm neo đặc trưng.",
    (
        "*",
        "Feature anchors do not span a valid boundary.",
    ): "Các điểm neo đặc trưng không tạo thành ranh giới hợp lệ.",
    (
        "*",
        "Feature-aware sampling returned the wrong point count.",
    ): "Lấy mẫu có nhận diện đặc trưng trả về số điểm không đúng.",
    (
        "*",
        "The strip plan contains no complete face sequence.",
    ): "Kế hoạch dải không có trình tự mặt nào hoàn chỉnh.",
    (
        "*",
        "The strip plan did not consume the full inner boundary.",
    ): "Kế hoạch dải không dùng hết toàn bộ ranh giới bên trong.",
    (
        "*",
        "The strip plan did not consume the full outer boundary.",
    ): "Kế hoạch dải không dùng hết toàn bộ ranh giới bên ngoài.",
    ("*", "The strip plan contains a degenerate face."): "Kế hoạch dải chứa một mặt suy biến.",
    (
        "*",
        "Select a continuous chain of edges or points.",
    ): "Hãy chọn một chuỗi liên tục các cạnh hoặc điểm.",
    (
        "*",
        "The selected edges cross each other.  Keep only one direction of them.",
    ): "Các cạnh đã chọn cắt nhau. Hãy chỉ giữ một hướng trong số đó.",
    (
        "*",
        "The selected edges are not joined, so they cannot form one continuous chain.",
    ): "Các cạnh đã chọn không nối nhau nên không tạo thành một chuỗi liên tục.",
    (
        "*",
        "The selected edges are not continuous; there is a gap in between.",
    ): "Các cạnh đã chọn không liên tục; có khoảng trống ở giữa.",
    (
        "*",
        "The selected edges close back into a ring.  Break the loop and try again.",
    ): "Các cạnh đã chọn khép lại thành một vòng. Hãy phá vòng lặp rồi thử lại.",
    (
        "*",
        "No valid ordered strip path was found.",
    ): "Không tìm thấy đường dẫn dải có thứ tự hợp lệ.",
    (
        "*",
        "The ordered strip contains intersecting edges.",
    ): "Dải có thứ tự chứa các cạnh giao cắt nhau.",
    ("*", "The inner curve has too few points."): "Đường cong bên trong quá ít điểm.",
    ("*", "The outer curve has too few points."): "Đường cong bên ngoài quá ít điểm.",
    (
        "*",
        "The faces beside this chain all close in on one point, so it has to be "
        "resampled as a whole ring.",
    ): (
        "Các mặt bên cạnh chuỗi này đều co về cùng một điểm, nên phải lấy mẫu lại cả một "
        "vòng khép kín."
    ),
    (
        "*",
        "This chain of edges does not run between two matching strips of faces, so "
        "there is nothing here to resample.",
    ): (
        "Chuỗi cạnh này không chạy giữa hai dải mặt khớp nhau, nên ở đây không có gì để "
        "lấy mẫu lại."
    ),
    (
        "*",
        "The selected path contains a branch that cannot be resampled safely.",
    ): "Đường dẫn đã chọn chứa một nhánh không thể lấy mẫu lại an toàn.",
    (
        "*",
        "The target path would duplicate an existing edge.",
    ): "Đường dẫn mục tiêu sẽ nhân đôi một cạnh đã có.",
    ("*", "The triangle-fan cap is no longer valid."): "Nắp quạt tam giác không còn hợp lệ.",
    (
        "*",
        "An n-gon cap needs at least three boundary vertices.",
    ): "Nắp n-gon cần tối thiểu ba đỉnh thuộc ranh giới.",
    (
        "*",
        "The n-gon cap boundary contains duplicate points.",
    ): "Ranh giới của nắp n-gon chứa các điểm trùng nhau.",
    (
        "*",
        "The n-gon cap boundary is degenerate or self-intersecting.",
    ): "Ranh giới của nắp n-gon bị suy biến hoặc tự giao cắt.",
    (
        "*",
        "The n-gon cap would contain a degenerate triangle.",
    ): "Nắp n-gon sẽ chứa một hình tam giác suy biến.",
    (
        "*",
        "The source no longer matches the locked selection.",
    ): "Nguồn không còn khớp với lựa chọn đã khóa.",
    (
        "*",
        "Select one path or multiple quad-connected parallel paths.",
    ): "Hãy chọn một đường dẫn, hoặc nhiều đường dẫn song song nối bằng tứ giác.",
    (
        "*",
        "Nothing here can be resampled.  Select a continuous chain of edges or points.",
    ): (
        "Không có gì ở đây có thể lấy mẫu lại. Hãy chọn một chuỗi liên tục các cạnh hoặc "
        "điểm."
    ),
}
