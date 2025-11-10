"""Home Assistant platform for eKartoteka sensors using DataUpdateCoordinator.

This module exposes:
- eKartotekaMeterSensor: per-apartment meter readings (water/energy)
- eKartotekaInvoiceSummarySensor: per-house sum of yearly meters invoice value

Both YAML (async_setup_platform) and Config Entry (async_setup_entry) flows
are supported. API calls are consolidated via a DataUpdateCoordinator
per house to minimize load and keep entities in sync.
"""
from __future__ import annotations

import logging
import traceback
from datetime import timedelta
from typing import Callable, Optional

import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from homeassistant.components.sensor import (
    SensorEntity,
    PLATFORM_SCHEMA,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .ekartoteka_api import eKartotekaAPI
from .meter_sensor import EkartotekaMeterSensor
from .invoice_entry_sensor import EkartotekaRentInvoiceEntry
from .meter_sensor_cost import EkartotekaMeterSensorCost
from .utility_summary_sensor import EkartotekaInvoiceSummarySensor
from .coordinator import EkartotekaCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
    }
)

# Default polling cadence for the coordinator
SCAN_INTERVAL = timedelta(hours=24)

# -------------------------
# Setup routines
# -------------------------
async def _async_build_entities_for_house(
    hass: HomeAssistant, api: eKartotekaAPI, house: dict
) -> list[SensorEntity]:
    entities: list[SensorEntity] = []
    try:
        if house.get("IdADo") is None:
            _LOGGER.warning("Skipping house without IdADo: %s", house)
            return entities

        coordinator = EkartotekaCoordinator(hass, api, house)
        # Ensure we have data before creating entities
        await coordinator.async_config_entry_first_refresh()

        # Per-house invoice summary
        meters_info = await hass.async_add_executor_job(api.houseAnalysisSummary, coordinator.house_id)
        for meter in meters_info:
            if meter.get("id_el_op", None):
                entities.append(
                    EkartotekaInvoiceSummarySensor(
                        coordinator,
                        meter.get("id_el_op"),
                        meter.get("Nazwa", "")
                    )
                )
                _LOGGER.error("test")
                # Monthly cost per sensor
                entities.append(
                    EkartotekaMeterSensorCost(
                        coordinator=coordinator,
                        sensor_id=meter.get("id_el_op"),
                        sensor_name=meter.get("Nazwa", ""),
                    )
                )

        # Last invoice data per last update from coordinator
        last_invoice = coordinator.data.get("last_invoice", {})
        for entry_name, entry in last_invoice.items():
            entities.append(EkartotekaRentInvoiceEntry(coordinator, entry_name, entry.get("apartment_id")))

        # Per-apartment meter entities based on coordinator meta
        meters = coordinator.data.get("meters", {})

        # We need unit and names -> fetch once from houseSensorList
        sensors = await hass.async_add_executor_job(api.houseSensorList, coordinator.house_id)
        sensor_meta_by_id = {
            int(s.get("id_el_op")): {
                "group_id": s.get("id_gru"),
                "unit": (s.get("jm") or "").strip(),
                "name": s.get("nazwa") or str(s.get("id_el_op"))
            }
            for s in sensors
            if s.get("id_el_op") is not None
        }

        for (apt_id, sensor_id), _ in meters.items():
            meta = sensor_meta_by_id.get(int(sensor_id))
            if not meta:
                continue
            entities.append(
                EkartotekaMeterSensor(
                    coordinator=coordinator,
                    apartment_id=int(apt_id),
                    sensor_id=int(sensor_id),
                    group_id=int(meta.get("group_id")) if meta.get("group_id") is not None else 0,
                    unit=meta.get("unit", ""),
                    sensor_name=meta.get("name", str(sensor_id)),
                )
            )
    except Exception as err:
        _LOGGER.error(traceback.format_exc())
    return entities


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities,
) -> None:
    user = config_entry.data[CONF_USERNAME]
    password = config_entry.data[CONF_PASSWORD]
    api = eKartotekaAPI(user, password)

    try:
        houses = await hass.async_add_executor_job(api.houseList)
    except Exception as err:
        _LOGGER.error("Failed to fetch house list: %s", err)
        return

    if not houses:
        _LOGGER.warning("No houses returned by API")
        return

    all_entities: list[SensorEntity] = []
    _LOGGER.debug("Loading houses (config entry)")
    for house in houses:
        entities = await _async_build_entities_for_house(hass, api, house)
        all_entities.extend(entities)

    if all_entities:
        async_add_entities(all_entities)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: Callable,
    discovery_info: Optional[DiscoveryInfoType] = None,
) -> None:
    api = eKartotekaAPI(config.get(CONF_USERNAME), config.get(CONF_PASSWORD))

    try:
        houses = await hass.async_add_executor_job(api.houseList)
    except Exception as err:
        _LOGGER.error("Failed to fetch house list: %s", err)
        return

    if not houses:
        _LOGGER.warning("No houses returned by API")
        return

    all_entities: list[SensorEntity] = []
    _LOGGER.debug("Loading houses")
    for house in houses:
        entities = await _async_build_entities_for_house(hass, api, house)
        all_entities.extend(entities)

    if all_entities:
        async_add_entities(all_entities)

