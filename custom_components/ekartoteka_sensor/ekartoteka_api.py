""" 
eKartoteka API wrapper used by the sensor platform.

Notes
-----
- Uses a single `requests.Session` for connection reuse, with automatic
  retries (backoff) for connection errors, timeouts, 429 and 5xx responses.
- Token state is shared between executor threads and guarded by a lock.
- Two token types are used by the backend:
  * auth_token: acquired via `/api-token-auth/`, used to fetch account metadata
  * token:      per-account token returned in account details; used for most data queries
- Timestamps for cache-busting params use `now(timezone.utc).timestamp() * 1000`.
"""
from __future__ import annotations

from typing import Dict, Any, Optional
from datetime import datetime, timezone
import threading
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
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

# ---------- Transport settings ----------
# (connect, read) timeouts in seconds
REQUEST_TIMEOUT = (10, 30)
# Statuses treated as "expired/invalid token" -> re-login and retry once
AUTH_ERROR_STATUSES = (401, 403)


class eKartotekaError(Exception):
    """Raised when the eKartoteka API returns an unusable response."""


class eKartotekaAuthError(eKartotekaError):
    """Raised when login fails or the API rejects freshly issued tokens."""


def _build_session() -> requests.Session:
    """Session that retries transient network errors, 429 and 5xx with backoff."""
    retry = Retry(
        total=4,
        connect=4,
        read=3,
        status=4,
        backoff_factor=2,  # 0s, 4s, 8s, 16s between attempts
        status_forcelist=(429, 500, 502, 503, 504),
        # Every call here only reads data; login POST is safe to repeat too
        allowed_methods=frozenset({"GET", "POST"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


class eKartotekaAPI:
    """Thin wrapper around eKartoteka REST endpoints.

    One instance is shared by all house coordinators, whose calls run in
    Home Assistant's executor threads, so token state and the session are
    guarded by `_lock`.
    """

    def __init__(self, username: str, password: str) -> None:
        self.username = username
        self.password = password
        self.session = _build_session()
        self._lock = threading.RLock()

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
        return int(datetime.now(timezone.utc).timestamp() * 1000)

    def _bearer(self, tok: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {tok}"} if tok else {}

    def _send(self, method: str, url: str, token: str, json: Optional[dict] = None) -> requests.Response:
        headers = {**self._json_headers(), **self._bearer(token)}
        with self._lock:
            return self.session.request(method, url, headers=headers, json=json, timeout=REQUEST_TIMEOUT)

    @staticmethod
    def _parse(method: str, url: str, resp: requests.Response) -> Any:
        if resp.status_code != 200:
            raise eKartotekaError(f"{method} {url} failed: {resp.status_code} {resp.text[:200]}")
        try:
            return resp.json()
        except ValueError as err:
            raise eKartotekaError(
                f"{method} {url} returned non-JSON response: {resp.text[:200]}"
            ) from err

    def _request(self, method: str, url: str, json: Optional[dict] = None, *, use_account_token: bool = False) -> Any:
        """Request with automatic (re)login when the token is rejected.

        If `use_account_token` is True, uses `self.token`, otherwise `self.auth_token`.
        """
        self.login()
        token = self.token if use_account_token else self.auth_token
        resp = self._send(method, url, token, json)
        if resp.status_code in AUTH_ERROR_STATUSES:
            with self._lock:
                # Another thread may have already refreshed the token
                current = self.token if use_account_token else self.auth_token
                if current == token:
                    _LOGGER.debug("Token rejected (%s), logging in again", resp.status_code)
                    self._reset_tokens()
                    self.login()
                token = self.token if use_account_token else self.auth_token
            resp = self._send(method, url, token, json)
        return self._parse(method, url, resp)

    def _get(self, url: str, *, use_account_token: bool = False) -> Any:
        return self._request("GET", url, use_account_token=use_account_token)

    def _post(self, url: str, json: Optional[dict] = None, *, use_account_token: bool = False) -> Any:
        return self._request("POST", url, json, use_account_token=use_account_token)

    def _reset_tokens(self) -> None:
        with self._lock:
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
        """Ensure both `auth_token` and per-account `token` are present.

        Uses raw requests (no re-login on 401) so it can't recurse, and only
        publishes tokens once the whole sequence succeeded.
        """
        with self._lock:
            if self.token and self.auth_token:
                return True

            # 1) Obtain auth_token
            payload = {"username": self.username, "password": self.password}
            resp = self._send("POST", login_url, "", payload)
            if resp.status_code in (400, *AUTH_ERROR_STATUSES):
                raise eKartotekaAuthError(
                    f"Authorization failed for {self.username}. Response {resp.status_code} {resp.text[:200]}"
                )
            auth_token = self._parse("POST", login_url, resp).get("token", "")
            if not auth_token:
                raise eKartotekaAuthError("Login response did not include auth token")

            # 2) Fetch accounts list using auth_token
            acc_list = self._parse("GET", accounts_list, self._send("GET", accounts_list, auth_token))
            results = acc_list.get("results", []) if isinstance(acc_list, dict) else []
            if not results:
                raise eKartotekaError("No linked accounts returned for user")
            if len(results) > 1:
                _LOGGER.debug("User has %s linked accounts, using the first one", len(results))
            account_id = results[0].get("id")
            if account_id is None:
                raise eKartotekaError("Linked account payload missing 'id'")

            # 3) Fetch account details -> provides per-account token
            url = account_details.format(account_id)
            details = self._parse("GET", url, self._send("GET", url, auth_token))
            token = details.get("token", "")
            if not token:
                raise eKartotekaAuthError("Account details did not include account token")
            id_kli = details.get("id_kli")

            # 4) Fetch groups for this client -> provides id_gru
            url = groups.format(id_kli)
            grps = self._parse("GET", url, self._send("GET", url, token))
            grp_list = grps.get("results", []) if isinstance(grps, dict) else []
            if not grp_list:
                raise eKartotekaError("Groups list empty for user")
            id_gru = grp_list[0].get("IdGru")
            if id_gru is None:
                raise eKartotekaError("Groups payload missing 'IdGru'")

            self.id_usr = details.get("id_usr")
            self.id_kli = id_kli
            self.id_gru = id_gru
            self.name = details.get("nazwa")
            self.auth_token = auth_token
            self.token = token
            return True
