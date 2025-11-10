from __future__ import annotations

import homeassistant.helpers.config_validation as cv
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorStateClass,
)

from .base_sensor import EkartotekaBaseEntity
from .coordinator import EkartotekaCoordinator

class EkartotekaMeterSensorCost(EkartotekaBaseEntity):
    _attr_should_poll = False
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "zl"
    _attr_device_class = SensorDeviceClass.MONETARY

    def __init__(
        self,
        coordinator: EkartotekaCoordinator,
        #apartment_id: int,
        sensor_id: int,
        #group_id: int,
        #unit: str,
        sensor_name: str,
    ) -> None:
        super().__init__(coordinator)
        #self.apartment_id = int(apartment_id)
        self.sensor_id = int(sensor_id)
        #self.group_id = int(group_id)
        self._attr_name = (
            f"{sensor_name} ({self.sensor_id})"
        )
        self._unique_id = (
            f"ekartoteka_meter_cost_{coordinator.house_id}_{self.sensor_id}"
        )

    @property
    def icon(self):
        return "mdi:cash"
    
    @property
    def unique_id(self) -> str | None:
        return self._unique_id

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {("eKartoteka_meter_sensor_cost", str(self.coordinator.house_id))},
            "name": f"Monthly utility bill for {self.coordinator.house_id}",
            "manufacturer": "eKartoteka",
            "model":  f"Monthly utility bill for {self.coordinator.house_id}",
            "via_device": None,
        }

    @property
    def native_value(self):
        value = self.coordinator.data.get("meters_invoice_summary", {}).get(self.sensor_id, None) if self.coordinator.data else {}
        return value.get("cost", None)
    
    @property
    def extra_state_attributes(self) -> dict:
        meters = self.coordinator.data.get("meters", {}) if self.coordinator.data else {}
        #sensor_data = meters.get((self.apartment_id, self.sensor_id), {})
        return {
            "house_id": self.coordinator.house_id,
            "house_name": self.coordinator.house_name,
        }

