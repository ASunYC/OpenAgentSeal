"""Official messaging channel adapters."""

from .dingtalk import DingTalkAdapter
from .discord import DiscordAdapter
from .feishu import FeishuAdapter
from .line import LineAdapter
from .qq import QQAdapter
from .slack import SlackAdapter
from .telegram import TelegramAdapter
from .wecom import WeComAdapter
from .whatsapp import WhatsAppAdapter

__all__ = [
    "DingTalkAdapter", "DiscordAdapter", "FeishuAdapter", "LineAdapter",
    "QQAdapter", "SlackAdapter", "TelegramAdapter", "WeComAdapter",
    "WhatsAppAdapter",
]
