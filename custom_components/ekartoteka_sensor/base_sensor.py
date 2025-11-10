from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.const import (
    UnitOfEnergy,
    UnitOfVolume,
)
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
)

from .coordinator import EkartotekaCoordinator

# -------------------------
# Sensors
# -------------------------
class EkartotekaBaseEntity(CoordinatorEntity[EkartotekaCoordinator], SensorEntity):
    """Common base with helpers for unit mapping."""

    def _apply_unit_mapping(self, unit: str | None) -> None:
        unit = (unit or "").strip()
        if unit == "m3":
            self._attr_device_class = SensorDeviceClass.WATER
            self._attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
        elif unit == "GJ":
            self._attr_device_class = SensorDeviceClass.ENERGY
            self._attr_native_unit_of_measurement = UnitOfEnergy.GIGA_JOULE
        else:
            self._attr_native_unit_of_measurement = unit or None

