"""Level 1 — a small rental FAQ bot implemented with fixed rules."""

from __future__ import annotations


def rule_based_bot(user_input: str) -> str:
    """Return a deterministic FAQ response without an LLM or tools."""

    text = (user_input or "").casefold()

    if any(word in text for word in ("chào", "hello", "xin chào", "hi ")):
        return (
            "Xin chào! Tôi là RentMate Level 1. Tôi trả lời được một số câu hỏi "
            "cố định về tiền cọc, hợp đồng và kinh nghiệm xem nhà."
        )

    if "tiền cọc" in text or "đặt cọc" in text:
        return (
            "Tiền cọc giúp bảo đảm nghĩa vụ thuê. Hãy yêu cầu hợp đồng ghi rõ "
            "số tiền cọc, điều kiện khấu trừ, thời điểm và cách hoàn tiền cọc."
        )

    if "hợp đồng" in text:
        return (
            "Hợp đồng nên ghi rõ giá thuê, thời hạn, tiền cọc, phí phát sinh, "
            "quyền sửa chữa, điều kiện chấm dứt và biên bản bàn giao."
        )

    if any(phrase in text for phrase in ("xem nhà", "kiểm tra phòng", "checklist")):
        return (
            "Khi xem nhà, hãy kiểm tra điện nước, thiết bị, an ninh, tiếng ồn, "
            "chi phí phát sinh và giấy tờ của bên cho thuê."
        )

    if any(phrase in text for phrase in ("tìm phòng", "tìm căn", "lịch trống")):
        return (
            "Level 1 không truy cập được dữ liệu căn đang cho thuê. Hãy dùng "
            "ReAct Agent để tìm căn và kiểm tra lịch xem."
        )

    if "đặt lịch" in text:
        return (
            "Level 1 không thể đặt lịch. Việc đặt lịch cần chọn căn, khung giờ "
            "và xác nhận thông tin qua ReAct Agent."
        )

    return (
        "Tôi chưa có luật phù hợp cho câu hỏi này. Bạn có thể hỏi về tiền cọc, "
        "hợp đồng, checklist xem nhà hoặc chuyển sang cấp AI cao hơn."
    )


if __name__ == "__main__":
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    for query in (
        "Xin chào",
        "Tôi cần lưu ý gì về tiền cọc?",
        "Tìm phòng ở Cầu Giấy",
    ):
        print(f"User: {query}")
        print(f"Bot : {rule_based_bot(query)}\n")
