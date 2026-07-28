import type { Booking } from "../types";
import { Icon } from "./Icon";
import { slotLabel } from "./SlotPicker";

interface BookingDrawerProps {
  bookings: Booking[];
  exportUrl: string;
  loading?: boolean;
  onClose: () => void;
}

export function BookingDrawer({
  bookings,
  exportUrl,
  loading,
  onClose
}: BookingDrawerProps) {
  return (
    <div className="drawer-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <aside aria-labelledby="booking-heading" className="booking-drawer">
        <div className="drawer-heading">
          <div>
            <p className="eyebrow">Lịch của phiên này</p>
            <h2 id="booking-heading">Các buổi xem đã đặt</h2>
          </div>
          <button aria-label="Đóng danh sách lịch" className="icon-button" onClick={onClose} type="button">
            <Icon name="close" size={20} />
          </button>
        </div>

        <div className="drawer-content">
          {loading ? (
            <div className="drawer-state">
              <span className="loading-mark" />
              <p>Đang đọc lịch đã đặt…</p>
            </div>
          ) : bookings.length ? (
            <ol className="booking-list">
              {bookings.map((booking) => (
                <li key={booking.booking_id}>
                  <div className="booking-calendar">
                    <Icon name="calendar" size={19} />
                  </div>
                  <div>
                    <p className="booking-property">Căn {booking.property_id}</p>
                    <h3>
                      {slotLabel({
                        slot_id: booking.slot_id,
                        property_id: booking.property_id,
                        starts_at: booking.starts_at
                      })}
                    </h3>
                    <p>
                      {booking.viewer_name ?? "Người xem"} ·{" "}
                      {booking.masked_phone ??
                        booking.phone_masked ??
                        booking.viewer_phone ??
                        "SĐT đã che"}
                    </p>
                    <span>{booking.status ?? "confirmed"}</span>
                  </div>
                </li>
              ))}
            </ol>
          ) : (
            <div className="drawer-state drawer-empty">
              <div className="empty-key">
                <Icon name="key" size={27} />
              </div>
              <h3>Chưa có lịch xem nào</h3>
              <p>Chọn một khung giờ ở hồ sơ căn hộ để bắt đầu.</p>
            </div>
          )}
        </div>

        <a className="export-button" download="rentmate-bookings.json" href={exportUrl}>
          <Icon name="download" size={18} />
          Tải lịch dạng JSON
        </a>
      </aside>
    </div>
  );
}
