from __future__ import annotations

import homeassistant.helpers.config_validation as cv
from homeassistant.components.sensor import (
    SensorStateClass,
)

from .base_sensor import EkartotekaBaseEntity
from .coordinator import EkartotekaCoordinator

# Utility usage sensor
class EkartotekaMeterSensor(EkartotekaBaseEntity):
    _attr_should_poll = False
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(
        self,
        coordinator: EkartotekaCoordinator,
        apartment_id: int,
        sensor_id: int,
        group_id: int,
        unit: str,
        sensor_name: str,
    ) -> None:
        super().__init__(coordinator)
        self.apartment_id = int(apartment_id)
        self.sensor_id = int(sensor_id)
        self.group_id = int(group_id)
        self._attr_name = (
            f"{sensor_name} ({self.sensor_id})"
        )
        self._unique_id = (
            f"ekartoteka_meter_{coordinator.house_id}_{self.apartment_id}_{self.group_id}_{self.sensor_id}"
        )
        self._apply_unit_mapping(unit)

    @property
    def icon(self):
        return "mdi:file-document"

    @property
    def unique_id(self) -> str | None:
        return self._unique_id

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {("eKartoteka_meter_sensor", str(self.sensor_id))},
            "name": f"{self._attr_name}",
            "manufacturer": "eKartoteka",
            "model": str(self.sensor_id),
            "via_device": None,
        }

    @property
    def native_value(self):
        meters = self.coordinator.data.get("meters", {}) if self.coordinator.data else {}
        return meters.get((self.apartment_id, self.sensor_id)).get("value", None)
    
    @property
    def extra_state_attributes(self) -> dict:
        meters = self.coordinator.data.get("meters", {}) if self.coordinator.data else {}
        sensor_data = meters.get((self.apartment_id, self.sensor_id), {})
        return {
            "type": sensor_data.get("type", None),
            "read_date": sensor_data.get("read_date", None),
            "house_id": self.coordinator.house_id,
            "house_name": self.coordinator.house_name,
            "apartment_id": self.apartment_id,
        }
