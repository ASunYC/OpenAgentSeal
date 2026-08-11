"""Channel-neutral durable messaging gateway."""

from .contracts import AuthenticatedGatewayFrame, ChannelAdapter, ChannelCapabilities, GatewayConnectorCapability, NormalizedInboundEvent, OutboundMessage
from .ingress import IngressLimits, IngressReceipt, IngressRunSummary, IngressService, IngressWorker
from .router import GatewayRouter, ResolvedRoute, RouteResolutionError

__all__ = [
    "ChannelAdapter",
    "AuthenticatedGatewayFrame",
    "ChannelCapabilities",
    "GatewayConnectorCapability",
    "GatewayRouter",
    "IngressReceipt",
    "IngressLimits",
    "IngressRunSummary",
    "IngressService",
    "IngressWorker",
    "NormalizedInboundEvent",
    "OutboundMessage",
    "ResolvedRoute",
    "RouteResolutionError",
]
