import { useEffect, useState, type FormEvent } from "react";
import type { ConfirmationContext, Property, ViewingSlot } from "../types";
import { Icon } from "./Icon";
import { slotLabel } from "./SlotPicker";

interface ConfirmationModalProps {
  property: Property;
  slot: ViewingSlot;
  onClose: () => void;
  onConfirm: (context: ConfirmationContext) => void;
  submitting?: boolean;
}

function isVietnamesePhone(phone: string) {
  const normalized = phone.replace(/[\s.-]/g, "");
  return /^(?:\+84|0)\d{9,10}$/.test(normalized);
}

export function ConfirmationModal({
  property,
  slot,
  onClose,
  onConfirm,
  submitting
}: ConfirmationModalProps) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [errors, setErrors] = useState<{ name?: string; phone?: string }>({});

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !submitting) onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose, submitting]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const nextErrors: { name?: string; phone?: string } = {};
    if (name.trim().length < 2) nextErrors.name = "Nhập tên người đi xem nhà.";
    if (!isVietnamesePhone(phone)) nextErrors.phone = "Nhập số điện thoại Việt Nam hợp lệ.";
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;

    onConfirm({
      accepted: true,
      property_id: property.property_id,
      slot_id: slot.slot_id,
      viewer_name: name.trim(),
      viewer_phone: phone.replace(/[\s.-]/g, "")
    });
  };

  return (
    <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section
        aria-describedby="confirmation-description"
        aria-labelledby="confirmation-title"
        aria-modal="true"
        className="confirmation-modal"
        role="dialog"
      >
        <div className="modal-heading">
          <div className="modal-key">
            <Icon name="key" size={22} />
          </div>
          <div>
            <p className="eyebrow">Cổng xác nhận</p>
            <h2 id="confirmation-title">Kiểm tra trước khi đặt lịch</h2>
          </div>
          <button
            aria-label="Đóng hộp xác nhận"
            className="icon-button"
            disabled={submitting}
            onClick={onClose}
            type="button"
          >
            <Icon name="close" size={20} />
          </button>
        </div>

        <p id="confirmation-description" className="modal-description">
          Chỉ khi bạn bấm “Xác nhận đặt lịch”, RentMate mới gửi hành động booking.
        </p>

        <dl className="confirmation-ticket">
          <div>
            <dt>Căn xem</dt>
            <dd>
              {property.title ?? `Căn ${property.property_id}`}
              <span>{property.property_id}</span>
            </dd>
          </div>
          <div>
            <dt>Khung giờ</dt>
            <dd>{slotLabel(slot)}</dd>
          </div>
        </dl>

        <form className="confirmation-form" onSubmit={submit}>
          <label htmlFor="viewer-name">
            <span>Người đi xem</span>
            <input
              autoComplete="name"
              autoFocus
              disabled={submitting}
              id="viewer-name"
              onChange={(event) => setName(event.target.value)}
              placeholder="Nguyễn An"
              value={name}
            />
            {errors.name ? <small role="alert">{errors.name}</small> : null}
          </label>
          <label htmlFor="viewer-phone">
            <span>Số điện thoại</span>
            <input
              autoComplete="tel"
              disabled={submitting}
              id="viewer-phone"
              inputMode="tel"
              onChange={(event) => setPhone(event.target.value)}
              placeholder="0912 345 678"
              value={phone}
            />
            {errors.phone ? <small role="alert">{errors.phone}</small> : null}
          </label>

          <div className="privacy-note">
            <Icon name="check" size={16} />
            Số điện thoại sẽ được che trong trace và file JSON xuất ra.
          </div>

          <div className="modal-actions">
            <button className="secondary-button" disabled={submitting} onClick={onClose} type="button">
              Xem lại
            </button>
            <button className="primary-button" disabled={submitting} type="submit">
              {submitting ? "Đang giữ lịch…" : "Xác nhận đặt lịch"}
              {!submitting ? <Icon name="arrow" size={18} /> : null}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
