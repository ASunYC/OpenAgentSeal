"""Channel-neutral durable messaging gateway."""

from .contracts import ChannelAdapter, ChannelCapabilities, NormalizedInboundEvent, OutboundMessage
from .router import GatewayRouter, ResolvedRoute, RouteResolutionError

__all__ = [
    "ChannelAdapter",
    "ChannelCapabilities",
    "GatewayRouter",
    "NormalizedInboundEvent",
    "OutboundMessage",
    "ResolvedRoute",
    "RouteResolutionError",
]
