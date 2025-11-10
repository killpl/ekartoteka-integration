""" 
eKartoteka API wrapper used by the sensor platform.

Notes
-----
- Uses a single `requests.Session` for connection reuse.
- Two token types are used by the backend:
  * auth_token: acquired via `/api-token-auth/`, used to fetch account metadata
  * token:      per-account token returned in account details; used for most data queries
- Timestamps for cache-busting params use `utcnow().timestamp() * 1000`.
"""
from __future__ import annotations

from typing import Dict, Any, Optional
from datetime import datetime
import requests
import logging

_LOGGER = logging.getLogger(__name__)

# ---------- Endpoints ----------
login_url = "https://www.e-kartoteka.pl/api/api-token-auth/"
accounts_list = "https://www.e-kartoteka.pl/api/konta/kontapowiazane/?pageSize=50"
account_details = "https://www.e-kartoteka.pl/api/konta/kontapowiazane/{0}/"
groups = "https://www.e-kartoteka.pl/api/uzytkownicy/grupy/?id_kli={0}&page=1&pageSize=100"
houses = "https://www.e-kartoteka.pl/api/uzytkownicy/nieruchomosci/?id_gru={0}&id_kli={1}&page=1&pageSize=20"
apartments = "https://www.e-kartoteka.pl/api/oplatymiesieczne/lokale/?page=1&pageSize=1000&id_a_do={0}&id_kli={1}&_={2}"

# Water / heat sensors
analysis_summary = "https://www.e-kartoteka.pl/api/media/analizazuzycia/?page=1&pageSize=20&id_a_do={0}&id_kli={1}&rok={2}&_={3}"
sensors_list = "https://www.e-kartoteka.pl/api/liczniki/rodzajemediow/?page=1&pageSize=20&id_a_do={0}&id_gru={1}&_={2}"
sensor_value = "https://www.e-kartoteka.pl/api/liczniki/liczniki/?page=1&pageSize=20&id_lok={0}&id_el_op={1}&_={2}"

# Rental fee
invoices_list = "https://www.e-kartoteka.pl/api/oplatymiesieczne/okresy/?page=1&pageSize=20&id_a_do={0}&id_kli={1}&id_lok={2}&_={3}"
monthly_rental = "https://www.e-kartoteka.pl/api/oplatymiesieczne/oplatymiesieczneb/?page=1&pageSize=100&id_nal={0}&id_lok={1}&id_kli={2}&_={3}"
monthly_meters_cost = "https://www.e-kartoteka.pl/api/media/rozliczeniemediow/?page=1&pageSize=20&id_a_do={0}&id_kli={1}&id_el_op={2}&ordering=DataOd&_={3}"

class eKartotekaAPI:
    """Thin wrapper around eKartoteka REST endpoints."""

    def __init__(self, username: str, password: str) -> None:
        self.username = username
        self.password = password
        self.session = requests.Session()

        # tokens/account metadata
        self.auth_token: str = ""
        self.token: str = ""
        self.id_usr: str | int | None = None
        self.id_kli: str | int | None = None
        self.id_gru: str | int | None = None
        self.name: str | None = None

    # ---------- helpers ----------
    @staticmethod
    def _json_headers() -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": "https://www.e-kartoteka.pl",
            "Referer": "https://www.e-kartoteka.pl/",
            "Host": "www.e-kartoteka.pl",
        }

    @staticmethod
    def _ts_ms() -> int:
        return int(datetime.utcnow().timestamp() * 1000)

    def _bearer(self, tok: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {tok}"} if tok else {}

    def _get(self, url: str, *, use_account_token: bool = False) -> Any:
        """GET with automatic (re)login on 401.

        If `use_account_token` is True, uses `self.token`, otherwise `self.auth_token`.
        """
        token = self.token if use_account_token else self.auth_token
        headers = {**self._json_headers(), **self._bearer(token)}
        resp = self.session.get(url, headers=headers, timeout=30)
        if resp.status_code == 401:
            # refresh tokens and retry once
            self._reset_tokens()
            self.login()
            token = self.token if use_account_token else self.auth_token
            headers = {**self._json_headers(), **self._bearer(token)}
            resp = self.session.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            raise Exception(f"GET {url} failed: {resp.status_code} {resp.text}")
        return resp.json()

    def _post(self, url: str, json: Optional[dict] = None, *, use_account_token: bool = False) -> Any:
        token = self.token if use_account_token else self.auth_token
        headers = {**self._json_headers(), **self._bearer(token)}
        resp = self.session.post(url, headers=headers, json=json, timeout=30)
        if resp.status_code == 401:
            self._reset_tokens()
            self.login()
            token = self.token if use_account_token else self.auth_token
            headers = {**self._json_headers(), **self._bearer(token)}
            resp = self.session.post(url, headers=headers, json=json, timeout=30)
        if resp.status_code != 200:
            raise Exception(f"POST {url} failed: {resp.status_code} {resp.text}")
        return resp.json()

    def _reset_tokens(self) -> None:
        self.auth_token = ""
        self.token = ""

    # ---------- public API ----------
    def houseList(self) -> Dict:
        self.login()
        data = self._get(
            houses.format(self.id_gru, self.id_kli), use_account_token=True
        )
        return data.get("results", [])

    def apartmentList(self, houseId: int | str) -> Dict:
        self.login()
        url = apartments.format(houseId, self.id_kli, self._ts_ms())
        data = self._get(url, use_account_token=True)
        return data.get("results", [])

    # Whole house analysis summary (sensors)
    def houseAnalysisSummary(self, houseId: int | str) -> Dict:
        self.login()
        url = analysis_summary.format(houseId, self.id_kli, datetime.now().year, self._ts_ms())
        data = self._get(url, use_account_token=True)
        return data.get("results", [])

    # House invoices list
    def houseInvoicesList(self, houseId: int | str, apartmentId: int | str) -> Dict:
        self.login()
        url = invoices_list.format(houseId, self.id_kli, apartmentId, self._ts_ms())
        data = self._get(url, use_account_token=True)
        return data.get("results", [])

    def invoiceDetails(self, apartmentId: int | str, invoiceId: int | str) -> Dict:
        self.login()
        url = monthly_rental.format(invoiceId, apartmentId, self.id_kli, self._ts_ms())
        data = self._get(url, use_account_token=True)
        return data.get("results", [])

    def houseSensorList(self, houseId: int | str) -> Dict:
        self.login()
        # NOTE: original code mistakenly passed a year here; the endpoint takes houseId, groupId, ts
        url = sensors_list.format(houseId, self.id_gru, self._ts_ms())
        data = self._get(url, use_account_token=True)
        return data.get("results", [])

    def houseSensorValue(self, apartmentId: int | str, sensorId: int | str) -> Dict:
        self.login()
        url = sensor_value.format(apartmentId, sensorId, self._ts_ms())
        data = self._get(url, use_account_token=True)
        return data.get("results", [])
    
    def houseSensorCost(self, houseId: int | str, sensorId: int | str) -> Dict:
        self.login()
        url = monthly_meters_cost.format(houseId, self.id_kli, sensorId, self._ts_ms())
        data = self._get(url, use_account_token=True)
        return data.get("results", [])


    # ---------- auth ----------
    def login(self) -> bool:
        """Ensure both `auth_token` and per-account `token` are present."""
        if self.token and self.auth_token:
            return True

        # 1) Obtain auth_token
        payload = {"username": self.username, "password": self.password}
        resp = self.session.post(login_url, headers=self._json_headers(), json=payload, timeout=30)
        if resp.status_code != 200:
            raise Exception(
                f"Authorization failed for {self.username}. Response {resp.status_code} {resp.text}"
            )
        self.auth_token = resp.json().get("token", "")
        if not self.auth_token:
            raise Exception("Login response did not include auth token")

        # 2) Fetch accounts list using auth_token
        acc_list = self._get(accounts_list, use_account_token=False)
        results = acc_list.get("results", []) if isinstance(acc_list, dict) else []
        if not results:
            raise Exception("No linked accounts returned for user")
        account_id = results[0].get("id")
        if account_id is None:
            raise Exception("Linked account payload missing 'id'")

        # 3) Fetch account details -> provides per-account token
        details = self._get(account_details.format(account_id), use_account_token=False)
        self.id_usr = details.get("id_usr")
        self.id_kli = details.get("id_kli")
        self.name = details.get("nazwa")
        self.token = details.get("token", "")
        if not self.token:
            raise Exception("Account details did not include account token")

        # 4) Fetch groups for this client -> provides id_gru
        grps = self._get(groups.format(self.id_kli), use_account_token=True)
        grp_list = grps.get("results", []) if isinstance(grps, dict) else []
        if not grp_list:
            raise Exception("Groups list empty for user")
        self.id_gru = grp_list[0].get("IdGru")
        if self.id_gru is None:
            raise Exception("Groups payload missing 'IdGru'")

        return True
