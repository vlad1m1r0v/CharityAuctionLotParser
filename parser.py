from __future__ import annotations

import re
from typing import Optional

from models import Bid, Lot

LOT_RE = re.compile(r"Лот\s*#\s*(\d+)", re.IGNORECASE)
PRICE_RE = re.compile(r"Стартова\s+ціна\s*:\s*(.+)", re.IGNORECASE)
NUMBER_RE = re.compile(r"\d+")


def parse_lot(text: str) -> Optional[Lot]:
    match = LOT_RE.search(text)
    if match is None:
        return None

    lines = text.split("\n")
    lot_idx = _line_index(lines, LOT_RE)
    price_idx = _line_index(lines, PRICE_RE)
    title_end = len(lines) if price_idx is None else price_idx

    return Lot(
        number=int(match.group(1)),
        title="\n".join(lines[lot_idx + 1 : title_end]).strip(),
        start_price=_extract_start_price(lines, price_idx),
        link="",
        message_id=0,
    )


def _line_index(lines: list[str], pattern: re.Pattern[str]) -> Optional[int]:
    return next((i for i, line in enumerate(lines) if pattern.search(line)), None)


def _extract_start_price(lines: list[str], price_idx: Optional[int]) -> int:
    if price_idx is None:
        return 0
    price_match = PRICE_RE.search(lines[price_idx])
    digits = NUMBER_RE.search(price_match.group(1)) if price_match else None
    return int(digits.group()) if digits else 0


def parse_bid(text: Optional[str]) -> Optional[int]:
    numbers = NUMBER_RE.findall(text) if text else []
    return max(map(int, numbers), default=None)


def determine_winner(bids: list[Bid]) -> Optional[Bid]:
    best_per_user = _best_bid_per_user(bids)
    return max(
        best_per_user.values(),
        key=lambda bid: (bid.amount, -bid.timestamp.timestamp(), -bid.message_id),
        default=None,
    )


def _best_bid_per_user(bids: list[Bid]) -> dict[int, Bid]:
    best: dict[int, Bid] = {}
    for bid in bids:
        current = best.get(bid.user_id)
        if current is None or bid.amount > current.amount:
            best[bid.user_id] = bid
    return best
