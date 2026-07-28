import type { ViewingSlot } from "../types";
import { Icon } from "./Icon";

export function slotLabel(slot: ViewingSlot) {
  const raw = slot.starts_at ?? slot.start_time;
  if (raw) {
    const date = new Date(raw);
    if (!Number.isNaN(date.getTime())) {
      return new Intl.DateTimeFormat("vi-VN", {
        weekday: "short",
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "Asia/Ho_Chi_Minh"
      }).format(date);
    }
    return raw;
  }
  return [slot.date, slot.time].filter(Boolean).join(" · ") || slot.slot_id;
}

interface SlotPickerProps {
  slots: ViewingSlot[];
  onSelect: (slot: ViewingSlot) => void;
}

export function SlotPicker({ slots, onSelect }: SlotPickerProps) {
  const availableSlots = slots.filter((slot) => slot.available !== false);
  if (!availableSlots.length) return null;

  return (
    <section className="slot-section" aria-labelledby="slot-heading">
      <div className="rail-section-heading">
        <div>
          <p className="eyebrow">Bước tiếp theo</p>
          <h2 id="slot-heading">Lịch xem còn trống</h2>
        </div>
        <span className="count-badge">{availableSlots.length}</span>
      </div>
      <p className="slot-intro">
        Chọn một khung giờ. RentMate sẽ cho bạn kiểm tra lại toàn bộ thông tin trước khi đặt.
      </p>
      <div className="slot-grid">
        {availableSlots.map((slot) => (
          <button className="slot-button" key={slot.slot_id} onClick={() => onSelect(slot)} type="button">
            <Icon name="calendar" size={16} />
            <span>{slotLabel(slot)}</span>
            <Icon className="slot-arrow" name="arrow" size={15} />
          </button>
        ))}
      </div>
    </section>
  );
}
