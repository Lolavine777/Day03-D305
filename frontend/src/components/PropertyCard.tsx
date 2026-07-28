import type { Property } from "../types";
import { Icon } from "./Icon";

const money = new Intl.NumberFormat("vi-VN", {
  style: "currency",
  currency: "VND",
  maximumFractionDigits: 0
});

function toneFor(id: string) {
  const value = [...id].reduce((total, character) => total + character.charCodeAt(0), 0);
  return `tone-${(value % 3) + 1}`;
}

interface PropertyCardProps {
  property: Property;
  onCheckSlots: (property: Property) => void;
}

export function PropertyCard({ property, onCheckSlots }: PropertyCardProps) {
  const price = property.price_vnd ?? property.monthly_rent_vnd ?? property.price;
  const area = property.area_m2 ?? property.area;
  const location = [property.district, property.city].filter(Boolean).join(", ");

  return (
    <article className="property-card">
      <div className={`property-facade ${toneFor(property.property_id)}`}>
        <div className="facade-grid" aria-hidden="true">
          <span />
          <span />
          <span />
          <span />
          <span />
          <span />
        </div>
        <p className="property-code">{property.property_id}</p>
        <p className="property-price">{price ? money.format(price) : "Liên hệ"}</p>
      </div>

      <div className="property-body">
        <div className="property-title-row">
          <div>
            <p className="property-kicker">{property.property_type ?? "Chỗ ở cho thuê"}</p>
            <h3>{property.title ?? `Căn ${property.property_id}`}</h3>
          </div>
          <span className={`availability ${property.available === false ? "is-off" : ""}`}>
            {property.available === false ? "Tạm hết" : "Đang trống"}
          </span>
        </div>

        <p className="property-location">
          <Icon name="location" size={16} />
          {property.address || location || "Địa chỉ đang cập nhật"}
        </p>

        <div className="property-facts">
          {area ? <span>{area} m²</span> : null}
          {property.deposit_months ? <span>Cọc {property.deposit_months} tháng</span> : null}
          {location && property.address ? <span>{location}</span> : null}
        </div>

        {property.amenities?.length ? (
          <ul className="amenity-list" aria-label="Tiện ích">
            {property.amenities.slice(0, 4).map((amenity) => (
              <li key={amenity}>{amenity}</li>
            ))}
          </ul>
        ) : null}

        <button
          className="text-button"
          disabled={property.available === false}
          onClick={() => onCheckSlots(property)}
          type="button"
        >
          <Icon name="calendar" size={18} />
          Kiểm tra lịch xem
          <Icon className="button-arrow" name="arrow" size={17} />
        </button>
      </div>
    </article>
  );
}
