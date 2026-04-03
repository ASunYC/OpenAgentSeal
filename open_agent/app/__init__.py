"""
Open Agent Application Module

This module provides the FastAPI application and related components
for the web UI, following the CoPaw architecture pattern.
"""

from open_agent.app._app import create_app, get_app
from open_agent.app.runner import AgentRunner, ChatManager, get_chat_manager

__all__ = [
    "create_app",
    "get_app",
    "AgentRunner",
    "ChatManager", 
    "get_chat_manager",
]