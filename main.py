from __future__ import annotations

import asyncio

from config import load_config
from exporter import export_results
from logging_config import get_logger, setup_logging
from models import LotResult
from parser import determine_winner, parse_lot
from telegram_client import TelegramService

logger = get_logger(__name__)


async def run() -> str:
    logger.info("Завантаження конфігурації...")
    config = load_config()
    logger.info("Конфігурація завантажена. Дата початку: %s", config.start_date)

    results: list[LotResult] = []

    async with TelegramService(config) as service:
        channel = await service.find_channel()
        messages = await service.iter_lot_messages(channel)
        logger.info("Знайдено лотів: %d", len(messages))

        for message in messages:
            result = await _process_lot(service, channel, message)
            if result is not None:
                results.append(result)

    results.sort(key=lambda item: item.lot.number)
    path = export_results(results)
    logger.info("Звіт збережено: %s", path)
    return path


async def _process_lot(service: TelegramService, channel, message) -> LotResult | None:
    try:
        lot = parse_lot(message.text or "")
        if lot is None:
            return None

        lot.message_id = message.id
        lot.link = service.build_lot_link(channel, message.id)

        logger.info("Знайдено лот #%s", lot.number)
        logger.info("Стартова ставка: %s грн", lot.start_price)

        comments = await service.get_comments(channel, message)
        logger.info("Отримано %d коментарів", len(comments))

        bids = await service.build_bids(comments)
        for bid in bids:
            logger.info("Ставка: %s -> %s", bid.full_name, bid.amount)

        winner = determine_winner(bids)
        if winner is not None:
            logger.info("Переможець: %s -> %s", winner.full_name, winner.amount)
        else:
            logger.warning("Лот #%s не має валідних ставок (коментарів: %d)", lot.number, len(comments))

        logger.info("Лот #%s додано до звіту", lot.number)
        return LotResult(lot=lot, winner=winner, comment_count=len(comments), bids=bids)
    except Exception as exc:  # noqa: BLE001 - один лот не має зривати прогін
        logger.warning("Не вдалося обробити лот (msg_id=%s): %s", getattr(message, "id", "?"), exc)
        return None


def main() -> None:
    setup_logging()
    asyncio.run(run())


if __name__ == "__main__":
    main()
