"""
Telegram Channel Provider.

Implements the ChannelProvider interface for Telegram integration.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..base import (
    ChannelConfigError,
    ChannelConnectionError,
    ChannelProvider,
    ChannelStatus,
    InboundMessage,
    MessageCallback,
    OutboundMessage,
    SendResult,
)

logger = logging.getLogger(__name__)

# python-telegram-bot is an optional dependency
try:
    from telegram import Update
    from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    Update = None
    Application = None


@dataclass
class TelegramConfig:
    """Configuration for Telegram provider."""

    token: str
    allowed_users: list[str] = field(default_factory=list)  # Empty = allow all
    allowed_chats: list[str] = field(default_factory=list)  # Empty = allow all
    max_response_length: int = 4096


class TelegramProvider(ChannelProvider):
    """
    Telegram channel provider using python-telegram-bot.

    Handles:
    - Private messages
    - Group messages (when bot is mentioned or replied to)
    """

    name = "telegram"
    display_name = "Telegram"

    def __init__(self):
        """Initialize Telegram provider."""
        if not TELEGRAM_AVAILABLE:
            raise ImportError(
                "python-telegram-bot is not installed. Install with: pip install python-telegram-bot"
            )

        self._app: Application | None = None
        self._config: TelegramConfig | None = None
        self._on_message: MessageCallback | None = None
        self._status = ChannelStatus(channel="telegram")
        self._task: asyncio.Task | None = None
        self._app_state: Any | None = None  # FastAPI app.state for command handlers

    async def start(
        self,
        config: Any,
        on_message: MessageCallback,
        app_state: Any | None = None,
    ) -> None:
        """
        Start the Telegram bot.

        Args:
            config: Telegram configuration (dict or TelegramConfig).
            on_message: Callback for inbound messages.
            app_state: FastAPI app.state for accessing registries in commands.
        """
        self._app_state = app_state
        if isinstance(config, dict):
            self._config = TelegramConfig(**config)
        elif isinstance(config, TelegramConfig):
            self._config = config
        else:
            self._config = TelegramConfig(token=config) if config else None

        if not self._config or not self._config.token:
            raise ChannelConfigError("Telegram token is required", "telegram")

        self._on_message = on_message

        # Build application
        self._app = Application.builder().token(self._config.token).build()

        # Add handlers
        self._app.add_handler(CommandHandler("start", self._handle_start))
        self._app.add_handler(CommandHandler("help", self._handle_help))
        self._app.add_handler(CommandHandler("skills", self._handle_skills))
        self._app.add_handler(MessageHandler(
            (filters.TEXT | filters.PHOTO | filters.Document.ALL | filters.VIDEO) & ~filters.COMMAND,
            self._handle_message,
        ))

        # Start polling in background
        try:
            await self._app.initialize()
            await self._app.start()
            self._task = asyncio.create_task(self._app.updater.start_polling(drop_pending_updates=True))

            self._status.running = True
            self._status.last_start = datetime.now(UTC)
            self._status.last_error = None
            logger.info("Telegram bot started")
        except Exception as e:
            self._status.last_error = str(e)
            raise ChannelConnectionError(f"Telegram connection failed: {e}", "telegram")

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        if self._app:
            try:
                await self._app.updater.stop()
                await self._app.stop()
                await self._app.shutdown()
            except Exception as e:
                logger.warning("Error stopping Telegram: %s", e)
            self._app = None

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        self._status.running = False
        self._status.last_stop = datetime.now(UTC)
        logger.info("Telegram bot stopped")

    async def send(self, message: OutboundMessage) -> SendResult:
        """
        Send a message through Telegram.

        Args:
            message: The outbound message.

        Returns:
            SendResult indicating success/failure.
        """
        if not self._app:
            return SendResult(success=False, error="Telegram not connected")

        try:
            chat_id = int(message.target)

            # Chunk message if needed
            chunks = self._chunk_message(message.content)

            # Try to use reply_to_id only if it's a valid Telegram message ID (numeric)
            reply_msg_id = None
            if message.reply_to_id:
                try:
                    reply_msg_id = int(message.reply_to_id)
                except ValueError:
                    # reply_to_id is a UUID, not a Telegram message ID - skip threading
                    pass

            sent_message = None
            for chunk in chunks:
                sent_message = await self._app.bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    reply_to_message_id=reply_msg_id,
                )

            self._status.last_outbound = datetime.now(UTC)
            self._status.message_count_out += 1

            return SendResult(
                success=True,
                message_id=str(sent_message.message_id) if sent_message else None,
            )

        except Exception as e:
            logger.error("Telegram send error: %s", e, exc_info=True)
            return SendResult(success=False, error=str(e))

    async def check_health(self) -> bool:
        """Check if Telegram is connected."""
        if not self._app:
            return False
        try:
            await self._app.bot.get_me()
            return True
        except Exception:
            return False

    def get_status(self) -> ChannelStatus:
        """Get current channel status."""
        return self._status

    def _chunk_message(self, content: str) -> list[str]:
        """Chunk message to fit Telegram's length limit."""
        max_len = self._config.max_response_length

        if len(content) <= max_len:
            return [content]

        chunks = []
        while content:
            if len(content) <= max_len:
                chunks.append(content)
                break

            # Find a good break point
            break_point = content.rfind("\n", 0, max_len)
            if break_point == -1:
                break_point = content.rfind(" ", 0, max_len)
            if break_point == -1:
                break_point = max_len

            chunks.append(content[:break_point])
            content = content[break_point:].lstrip()

        return chunks

    def _should_handle(self, update: Update) -> bool:
        """Check if we should handle this message."""
        if not update.effective_user:
            return False

        user_id = str(update.effective_user.id)
        chat_id = str(update.effective_chat.id)

        # Check user allowlist
        if self._config.allowed_users and user_id not in self._config.allowed_users:
            return False

        # Check chat allowlist
        if self._config.allowed_chats and chat_id not in self._config.allowed_chats:
            return False

        return True

    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        if not self._should_handle(update):
            return

        await update.message.reply_text(
            "Hello! I'm Ungula, your AI assistant. Send me a message and I'll respond.\n\n"
            "Type /help to see available commands."
        )

    async def _handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command."""
        if not self._should_handle(update):
            return

        await update.message.reply_text(
            "Available commands:\n"
            "/skills — List enabled skills\n"
            "/help — Show this message\n"
            "/start — Greeting\n\n"
            "Or just send a message to chat."
        )

    async def _handle_skills(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /skills command — list enabled skills."""
        if not self._should_handle(update):
            return

        if not self._app_state:
            await update.message.reply_text("Skills system not available.")
            return

        skill_registry = getattr(self._app_state, "skill_registry", None)
        if not skill_registry:
            await update.message.reply_text("Skills system not initialized.")
            return

        eligible = skill_registry.list_eligible()
        if not eligible:
            await update.message.reply_text("No skills currently enabled.")
            return

        lines = []
        for skill in eligible:
            emoji = skill.metadata.emoji or "-"
            name = skill.metadata.name
            desc = skill.metadata.description
            # Truncate long descriptions
            if len(desc) > 60:
                desc = desc[:57] + "..."
            lines.append(f"  {emoji} {name} — {desc}")

        text = f"Enabled skills ({len(eligible)}):\n" + "\n".join(lines)
        await update.message.reply_text(text)

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming text and media messages."""
        if not self._should_handle(update):
            return

        if not update.message:
            return

        # Extract content: use text, or caption for media messages
        content = update.message.text or update.message.caption or ""
        if not content and not (update.message.photo or update.message.document or update.message.video):
            return

        # Extract media URLs via Telegram file API
        media_urls: list[str] = []
        try:
            if update.message.photo:
                # Get highest resolution photo
                photo = update.message.photo[-1]
                file = await context.bot.get_file(photo.file_id)
                media_urls.append(file.file_path)
            if update.message.document:
                file = await context.bot.get_file(update.message.document.file_id)
                media_urls.append(file.file_path)
            if update.message.video:
                file = await context.bot.get_file(update.message.video.file_id)
                media_urls.append(file.file_path)
        except Exception as e:
            logger.warning("Failed to extract Telegram media URLs: %s", e)

        # Convert to InboundMessage
        is_private = update.effective_chat.type == "private"

        inbound = InboundMessage.create(
            channel="telegram",
            sender_id=str(update.effective_user.id),
            sender_name=update.effective_user.full_name or update.effective_user.username or str(update.effective_user.id),
            content=content,
            chat_type="direct" if is_private else "group",
            group_id=str(update.effective_chat.id) if not is_private else None,
            group_name=update.effective_chat.title if not is_private else None,
            reply_to_id=str(update.message.reply_to_message.message_id) if update.message.reply_to_message else None,
            media_urls=media_urls if media_urls else None,
            metadata={
                "chat_id": str(update.effective_chat.id),
                "message_id": str(update.message.message_id),
                "username": update.effective_user.username,
            },
        )

        # Update status
        self._status.last_inbound = datetime.now(UTC)
        self._status.message_count_in += 1

        # Dispatch to callback
        if self._on_message:
            try:
                await self._on_message(inbound)
            except Exception as e:
                logger.error("Error handling Telegram message: %s", e, exc_info=True)
