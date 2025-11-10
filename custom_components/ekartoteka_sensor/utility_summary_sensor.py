"""Home Assistant platform for eKartoteka sensors using DataUpdateCoordinator.

This module exposes:
- eKartotekaMeterSensor: per-apartment meter readings (water/energy)
- eKartotekaInvoiceSummarySensor: per-house sum of yearly meters invoice value

Both YAML (async_setup_platform) and Config Entry (async_setup_entry) flows
are supported. API calls are consolidated via a DataUpdateCoordinator
per house to minimize load and keep entities in sync.
"""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorStateClass,
)

from .base_sensor import EkartotekaBaseEntity
from .coordinator import EkartotekaCoordinator

class EkartotekaInvoiceSummarySensor(EkartotekaBaseEntity):
    _attr_should_poll = False
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "zl"
    _meter_id = None
    _attr_device_class = SensorDeviceClass.MONETARY

    def __init__(self, coordinator: EkartotekaCoordinator, meter_id: int, meter_name) -> None:
        super().__init__(coordinator)
        self._attr_name = (
            f"{meter_name} ({coordinator.house_id})"
        )
        self._unique_id = f"ekartoteka_meters_invoice_sum_{coordinator.house_id}_{meter_id}"
        self._meter_id = meter_id

    @property
    def icon(self):
        return "mdi:cash"

    @property
    def unique_id(self) -> str | None:
        return self._unique_id

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {("eKartoteka_meters_invoice_sensor", str(self.coordinator.house_id))},
            "name": f"Meters invoice yearly sum ({self.coordinator.house_id})",
            "manufacturer": "eKartoteka",
            "model": "meters_invoice_summary",
            "via_device": None,
        }

    @property
    def native_value(self):
        value = self.coordinator.data.get("meters_invoice_summary", {}).get(self._meter_id, None) if self.coordinator.data else {}
        return value.get("WynikRozliczenia", None)

    @property
    def extra_state_attributes(self) -> dict:
        value = self.coordinator.data.get("meters_invoice_summary", {}).get(self._meter_id, None) if self.coordinator.data else None
        return {
            "name": value.get("Nazwa", None),
            "house_id": self.coordinator.house_id,
            "house_name": self.coordinator.house_name,
        }
