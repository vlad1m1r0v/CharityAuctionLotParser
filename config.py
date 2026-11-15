from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime

from dotenv import load_dotenv

DATE_FORMATS = ("%Y-%m-%d", "%Y-%m-%d ", "%d.%m.%Y", "%Y.%m.%d")


@dataclass
class Config:
    api_id: int
    api_hash: str
    channel_name: str
    start_date: date


def _parse_date(raw: str) -> date:
    raw = raw.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(
        f"Некоректний формат START_DATE: {raw!r}. Очікується YYYY-MM-DD."
    )


def load_config(env_path: str = ".env") -> Config:
    load_dotenv(env_path)

    api_id_raw = os.getenv("API_ID")
    api_hash = os.getenv("API_HASH")
    channel_name = os.getenv("CHANNEL_NAME")
    start_date_raw = os.getenv("START_DATE")

    missing = [
        name
        for name, value in (
            ("API_ID", api_id_raw),
            ("API_HASH", api_hash),
            ("CHANNEL_NAME", channel_name),
            ("START_DATE", start_date_raw),
        )
        if not value
    ]
    if missing:
        raise ValueError(f"Відсутні обов'язкові змінні середовища: {', '.join(missing)}")

    try:
        api_id = int(api_id_raw)
    except ValueError as exc:
        raise ValueError(f"API_ID має бути цілим числом: {api_id_raw!r}") from exc

    return Config(
        api_id=api_id,
        api_hash=api_hash,
        channel_name=channel_name,
        start_date=_parse_date(start_date_raw),
    )
