from __future__ import annotations

import logging
import traceback
from datetime import timedelta

import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from homeassistant.components.sensor import (
    PLATFORM_SCHEMA,
)
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .ekartoteka_api import eKartotekaAPI

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
    }
)

# Default polling cadence for the coordinator
SCAN_INTERVAL = timedelta(hours=24)

class EkartotekaCoordinator(DataUpdateCoordinator[dict]):
    """Coordinator fetching data for a single house.

    coordinator.data schema:
    {
        "invoice_summary": dict
        "meters": dict
        "meta": { "house_id": int, "house_name": str }
    }
    """

    def __init__(self, hass: HomeAssistant, api: eKartotekaAPI, house: dict) -> None:
        self.hass = hass
        self.api = api
        self.house_id: int = int(house.get("IdADo"))
        self.house_name: str = (
            str(house.get("nazwa") or house.get("Nazwa") or self.house_id)
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"eKartoteka house {self.house_id}",
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> dict:
        """Fetch invoice summary and latest meter readings for all apartments."""
        try:
            # Fetch apartments for this house
            apartment_list = await self.hass.async_add_executor_job(
                self.api.apartmentList, self.house_id
            )

            # Fetch sensor list once per house (it appears shared across apartments)
            sensors = await self.hass.async_add_executor_job(
                self.api.houseSensorList, self.house_id
            )


            # Build latest values per (apartment_id, sensor_id)
            meters: dict[tuple[int, int], dict[str, str | float | int | None]] = {}
            last_invoice: dict[str, dict] = {}
            for apt in apartment_list:
                apt_id = apt.get("IdLok")
                if apt_id is None:
                    _LOGGER.warning("Empty IdLok in", apartment_list)
                    continue
                
                # Iterate over sensors
                for s in sensors:
                    sensor_id = s.get("id_el_op")
                    if sensor_id is None:
                        _LOGGER.warning("Empty sensor ", sensor_id, "in", s)
                        continue
                    # per original API shape: houseSensorValue(apartment_id, sensor_id)
                    values = await self.hass.async_add_executor_job(
                        self.api.houseSensorValue, apt_id, sensor_id
                    )
                    value = values[0].get("stan") if values else None
                    type = values[0].get("typ") if values else None
                    read_date = values[0].get("data") if values else None
                    
                    meters[(int(apt_id), int(sensor_id))] = {
                        "value": value,
                        "type": type,
                        "read_date": read_date
                    }

                # Iterate over last invoice
                invoices = await self.hass.async_add_executor_job(
                    self.api.houseInvoicesList, self.house_id, apt_id
                )
                if invoices and invoices[0].get("IdNal", None):
                    last_invoice_id = invoices[0].get("IdNal")

                    invoice_entries_list = await self.hass.async_add_executor_job(
                        self.api.invoiceDetails, apt_id, last_invoice_id
                    )
                    for entry in invoice_entries_list:
                        entry["start_date"] = invoices[0].get("DataOd", None)
                        entry["end_date"] = invoices[0].get("DataDo", None)
                        entry["paid"] = invoices[0].get("Stan", None)
                        entry["apartment_id"] = apt_id
                        last_invoice[entry.get("Nazwa")] = entry

            # Meters invoice summary for the house (for whole year increasing)
            meters_invoice_summary: dict[int, dict]= {}
            try:
                inv_list = await self.hass.async_add_executor_job(
                    self.api.houseAnalysisSummary, self.house_id
                )
                if inv_list:
                    for inv in inv_list:
                        _LOGGER.error(inv)
                        sensor_cost = await self.hass.async_add_executor_job(
                            self.api.houseSensorCost, self.house_id, inv["id_el_op"]
                        )
                        _LOGGER.error(sensor_cost)
                        if sensor_cost:
                            inv["cost"] = sensor_cost[0]["zuzycieFaktyczne"]
                            inv["amount"] = sensor_cost[0]["zuzycieFaktyczneJM"]
                        
                        meters_invoice_summary[inv["id_el_op"]] = inv
                        
            except Exception as inv_err:
                _LOGGER.warning(
                    "Invoice summary failed for house %s: %s", self.house_id, inv_err
                )

            return {
                "meters_invoice_summary": meters_invoice_summary,
                "meters": meters,
                "meta": {"house_id": self.house_id, "house_name": self.house_name},
                "last_invoice": last_invoice
            }

        except Exception as err:
            _LOGGER.error(traceback.format_exc())
            raise UpdateFailed(f"Unable to update eKartoteka data: {err}") from err

