from datetime import datetime, timezone


class CalendarClient:
    def __init__(self, creds_data: dict, event_history: list):
        self.creds_data = creds_data
        self.event_history = event_history
        calendar_id = creds_data.get("calendar_id", "primary")
        self.base_url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"

    def _get_token(self) -> str:
        import google.oauth2.credentials
        import google.auth.transport.requests
        credentials = google.oauth2.credentials.Credentials(
            token=None,
            refresh_token=self.creds_data["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self.creds_data["client_id"],
            client_secret=self.creds_data["client_secret"],
        )
        credentials.refresh(google.auth.transport.requests.Request())
        return credentials.token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._get_token()}", "Content-Type": "application/json"}

    def request(self, method: str, url: str, **kwargs) -> dict:
        import requests as http
        from fastapi import HTTPException
        resp = http.request(method, url, headers=self._headers(), **kwargs)
        if not resp.ok:
            raise HTTPException(status_code=502, detail=f"Calendar API {resp.status_code}: {resp.text}")
        return resp.json() if resp.content else {}

    def find_event(self, identifier: dict) -> dict | None:
        """
        Find an event by identifier. Returns one of:
          { event_id, summary, start }   — exactly one found
          { multiple: [...] }            — ambiguous
          None                           — not found
        """
        keywords = identifier.get("keywords", [])
        date_str = identifier.get("date")

        # 1. Check local history first
        candidates = []
        for ev in self.event_history:
            summary_lower = ev.get("summary", "").lower()
            if keywords and not any(kw.lower() in summary_lower for kw in keywords):
                continue
            if date_str and ev.get("start", "")[:10] != date_str:
                continue
            candidates.append(ev)

        if len(candidates) == 1:
            return candidates[0]

        # 2. Search Calendar API
        params: dict = {"singleEvents": "true", "orderBy": "startTime", "maxResults": 5}
        if keywords:
            params["q"] = " ".join(keywords)
        if date_str:
            params["timeMin"] = f"{date_str}T00:00:00+01:00"
            params["timeMax"] = f"{date_str}T23:59:59+01:00"
        else:
            params["timeMin"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        result = self.request("GET", self.base_url, params=params)
        items = result.get("items", [])

        if not items and candidates:
            return {"multiple": candidates}
        if len(items) == 1:
            ev = items[0]
            return {
                "event_id": ev["id"],
                "summary": ev.get("summary", ""),
                "start": ev["start"].get("dateTime", ev["start"].get("date", "")),
            }
        if len(items) > 1:
            return {
                "multiple": [
                    {"event_id": e["id"], "summary": e.get("summary", ""), "start": e["start"].get("dateTime", "")}
                    for e in items
                ]
            }
        return None

    def list_events(self, date_str: str) -> list:
        """Return all events on a specific date (YYYY-MM-DD)."""
        params = {
            "singleEvents": "true",
            "orderBy": "startTime",
            "timeMin": f"{date_str}T00:00:00+01:00",
            "timeMax": f"{date_str}T23:59:59+01:00",
            "maxResults": 20,
        }
        result = self.request("GET", self.base_url, params=params)
        return result.get("items", [])
