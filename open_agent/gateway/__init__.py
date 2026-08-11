"""Channel-neutral durable messaging gateway."""

from .contracts import ChannelAdapter, ChannelCapabilities, NormalizedInboundEvent, OutboundMessage
from .ingress import IngressReceipt, IngressRunSummary, IngressService, IngressWorker
from .router import GatewayRouter, ResolvedRoute, RouteResolutionError

__all__ = [
    "ChannelAdapter",
    "ChannelCapabilities",
    "GatewayRouter",
    "IngressReceipt",
    "IngressRunSummary",
    "IngressService",
    "IngressWorker",
    "NormalizedInboundEvent",
    "OutboundMessage",
    "ResolvedRoute",
    "RouteResolutionError",
]
