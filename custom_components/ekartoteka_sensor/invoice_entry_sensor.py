from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorStateClass,
)

from .base_sensor import EkartotekaBaseEntity
from .coordinator import EkartotekaCoordinator

class EkartotekaRentInvoiceEntry(EkartotekaBaseEntity):
    _attr_should_poll = False
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "zl"
    _meter_id = None
    _apartment_id = None
    _attr_device_class = SensorDeviceClass.MONETARY

    def __init__(self, coordinator: EkartotekaCoordinator, entry_name: str, apartment_id: int) -> None:
        super().__init__(coordinator)
        self._attr_name = (
            f"{entry_name} ({coordinator.house_id})"
        )
        self._unique_id = f"ekartoteka_invoice_entry_{coordinator.house_id}_{entry_name}"
        self._meter_id = entry_name
        self._apartment_id = apartment_id

    @property
    def icon(self):
        return "mdi:cash"

    @property
    def unique_id(self) -> str | None:
        return self._unique_id

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {("eKartoteka_last_invoice", str(self._apartment_id))},
            "name": f"Last invoice ({self.coordinator.house_id}.{self._apartment_id})",
            "manufacturer": "eKartoteka",
            "model": "last_invoice",
            "via_device": None,
        }

    @property
    def native_value(self):
        value = self.coordinator.data.get("last_invoice", {}).get(self._meter_id, None) if self.coordinator.data else {}
        return value.get("Nalicz", None)

    @property
    def extra_state_attributes(self) -> dict:
        value = self.coordinator.data.get("last_invoice", {}).get(self._meter_id, None) if self.coordinator.data else None
        return {
            "count": value.get("WspIle", None),
            "count_unit": value.get("WspIleJM", None),
            "price": value.get("Cena", None),
            "price_coefficent": value.get("WspCena", None),
            "is_sub": value.get("is_sub", None),
            "size": value.get("Ilosc", None),
            "unit": value.get("JM", None),
            "period": value.get("zaOkres", None),

            "period_start": value.get("start_date", None),
            "period_end": value.get("end_date", None),

            "name": value.get("Nazwa", None),
            "house_id": self.coordinator.house_id,
            "apartment_id": self._apartment_id,
            "house_name": self.coordinator.house_name
        }

