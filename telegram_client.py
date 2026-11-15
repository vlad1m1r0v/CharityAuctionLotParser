from __future__ import annotations

import asyncio
import getpass
from collections.abc import Awaitable, Callable
from datetime import datetime, time, timezone
from typing import Any

import qrcode
from telethon import TelegramClient, utils
from telethon.errors import (
    FloodWaitError,
    ServerError,
    SessionPasswordNeededError,
    TimedOutError,
)
from telethon.tl.functions.messages import GetDiscussionMessageRequest
from telethon.tl.types import Channel, Chat, Message, PeerUser

from config import Config
from logging_config import get_logger
from models import Bid
from parser import parse_bid, parse_lot

logger = get_logger(__name__)

SESSION_NAME = "auction_session"
QR_MAX_ATTEMPTS = 3
REQUEST_MAX_ATTEMPTS = 5


class TelegramService:
    def __init__(self, config: Config) -> None:
        self._config = config
        self.client = TelegramClient(SESSION_NAME, config.api_id, config.api_hash)

    async def __aenter__(self) -> "TelegramService":
        await self.start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.stop()

    async def start(self) -> None:
        await self._authorize()
        logger.info("Авторизація Telegram завершена.")

    async def _authorize(self) -> None:
        await self.client.connect()
        if await self.client.is_user_authorized():
            return

        for attempt in range(1, QR_MAX_ATTEMPTS + 1):
            qr_login = await self.client.qr_login()
            logger.info(
                "Відскануйте QR-код у Telegram (Налаштування → Пристрої → "
                "Підключити пристрій). Спроба %d/%d.",
                attempt,
                QR_MAX_ATTEMPTS,
            )
            logger.info("Або відкрийте посилання на пристрої, де ви вже авторизовані:")
            self._render_qr(qr_login.url)
            try:
                await qr_login.wait()
                return
            except asyncio.TimeoutError:
                logger.warning("QR-код протермінувався, генерую новий...")
            except SessionPasswordNeededError:
                password = getpass.getpass("Please enter your password: ")
                await self.client.sign_in(password=password)
                return

        raise RuntimeError("Не вдалося авторизуватися через QR-код.")

    @staticmethod
    def _render_qr(url: str) -> None:
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
        print(url)

    async def stop(self) -> None:
        await self.client.disconnect()

    async def find_channel(self) -> Channel | Chat:
        query = self._config.channel_name.strip().lower()
        matches = [
            dialog
            async for dialog in self.client.iter_dialogs()
            if isinstance(dialog.entity, (Channel, Chat))
            and query in (dialog.name or "").lower()
        ]

        if not matches:
            raise RuntimeError(f"Канал не знайдено за назвою: {self._config.channel_name!r}")

        if len(matches) > 1:
            logger.warning("Знайдено декілька каналів (%d). Використовую перший.", len(matches))
            for dialog in matches:
                logger.warning("  - %s", dialog.name)

        logger.info("Канал знайдено: %s", matches[0].name)
        return matches[0].entity

    async def iter_lot_messages(self, channel: Channel | Chat) -> list[Message]:
        offset = datetime.combine(self._config.start_date, time.min, tzinfo=timezone.utc)
        messages: list[Message] = []
        async for message in self.client.iter_messages(channel, reverse=True, offset_date=offset):
            if message.date.date() < self._config.start_date:
                continue
            if parse_lot(message.text or "") is not None:
                messages.append(message)
        return messages

    async def get_comments(self, channel: Channel | Chat, post: Message) -> list[Message]:
        discussion = await self._with_retry(
            f"обговорення лота (msg_id={post.id})",
            lambda: self.client(GetDiscussionMessageRequest(peer=channel, msg_id=post.id)),
        )
        if discussion is None or not discussion.messages:
            logger.warning("Для лота (msg_id=%s) не знайдено обговорення/коментарів.", post.id)
            return []

        root = min(discussion.messages, key=lambda msg: msg.id)
        peer = self._discussion_peer(discussion, root)
        comments = await self._with_retry(
            f"коментарі лота (msg_id={post.id})",
            lambda: self._fetch_comments(peer, root.id),
        )
        return comments or []

    @staticmethod
    def _discussion_peer(discussion: Any, root: Message) -> Any:
        channel_id = getattr(root.peer_id, "channel_id", None)
        chat = next(
            (chat for chat in discussion.chats if getattr(chat, "id", None) == channel_id),
            None,
        )
        return utils.get_input_peer(chat) if chat is not None else root.peer_id

    async def _fetch_comments(self, peer: Any, root_id: int) -> list[Message]:
        return [comment async for comment in self.client.iter_messages(peer, reply_to=root_id)]

    async def _with_retry(
        self, what: str, request: Callable[[], Awaitable[Any]]
    ) -> Any:
        for attempt in range(1, REQUEST_MAX_ATTEMPTS + 1):
            try:
                return await request()
            except FloodWaitError as exc:
                wait = exc.seconds + 1
                logger.warning("FloodWait %d с (%s), очікування...", wait, what)
                await asyncio.sleep(wait)
            except (ServerError, TimedOutError) as exc:
                logger.warning(
                    "Тимчасова помилка (%s) для %s, повторна спроба %d/%d...",
                    exc,
                    what,
                    attempt,
                    REQUEST_MAX_ATTEMPTS,
                )
                await asyncio.sleep(2 * attempt)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Не вдалося отримати %s: %s", what, exc)
                return None
        logger.warning("Не вдалося отримати %s після %d спроб.", what, REQUEST_MAX_ATTEMPTS)
        return None

    async def build_bids(self, comments: list[Message]) -> list[Bid]:
        bids: list[Bid] = []
        for comment in comments:
            amount = parse_bid(comment.text)
            if amount is None:
                continue

            sender = await self._resolve_sender(comment)
            if sender is None:
                logger.warning(
                    "Не вдалося визначити автора ставки %s (msg_id=%s, from_id=%s): %r",
                    amount,
                    comment.id,
                    getattr(comment, "from_id", None),
                    comment.text,
                )
                continue

            bids.append(self._to_bid(comment, amount, sender))
        return bids

    async def _resolve_sender(self, comment: Message) -> Any:
        sender = comment.sender
        if sender is not None:
            return sender

        try:
            return await comment.get_sender()
        except Exception:  # noqa: BLE001
            pass

        from_id = getattr(comment, "from_id", None)
        if isinstance(from_id, PeerUser):
            try:
                return await self.client.get_entity(from_id)
            except Exception:  # noqa: BLE001
                return None
        return None

    @staticmethod
    def _to_bid(comment: Message, amount: int, sender: Any) -> Bid:
        return Bid(
            user_id=getattr(sender, "id", 0),
            first_name=getattr(sender, "first_name", None) or getattr(sender, "title", ""),
            last_name=getattr(sender, "last_name", None),
            username=getattr(sender, "username", None),
            amount=amount,
            comment=comment.text,
            timestamp=comment.date,
            message_id=comment.id,
        )

    @staticmethod
    def build_lot_link(channel: Channel | Chat, message_id: int) -> str:
        username = getattr(channel, "username", None)
        if username:
            return f"https://t.me/{username}/{message_id}"

        peer_id = str(utils.get_peer_id(channel))
        if peer_id.startswith("-100"):
            internal = peer_id[4:]
        elif peer_id.startswith("-"):
            internal = peer_id[1:]
        else:
            internal = peer_id
        return f"https://t.me/c/{internal}/{message_id}" if internal else f"message_id={message_id}"
