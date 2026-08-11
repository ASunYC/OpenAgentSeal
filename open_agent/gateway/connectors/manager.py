"""Account-driven lifecycle manager for official long-lived connectors."""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, replace
from typing import Any, Callable

from open_agent.gateway.adapters import (
    DingTalkAdapter, DiscordAdapter, QQAdapter, WeComAdapter,
)
from open_agent.gateway.adapters.base_http import BoundedHttpTransport

from .contracts import ConnectorAuthenticationError, ConnectorSnapshot, parse_connector_credential
from .dingtalk import DingTalkStreamConnector
from .discord import DiscordGatewayConnector
from .qq import QQGatewayConnector
from .transport import DefaultConnectorNetwork
from .wecom import WeComAIBotConnector


CONNECTOR_KINDS = frozenset({"discord", "dingtalk", "qq", "wecom"})


@dataclass(frozen=True, slots=True)
class _Managed:
    credential_ref: str
    task: asyncio.Task[None]
    connector: Any


class ConnectorManager:
    """Reconciles enabled durable accounts with one fenced task per account."""

    def __init__(
        self,
        repository: Any,
        ingress: Any,
        credential_store: Any,
        adapters: dict[str, Any],
        destination_registry: Any,
        *,
        network_factory: Callable[[], Any] = DefaultConnectorNetwork,
        http_factory: Callable[[], Any] = BoundedHttpTransport,
        scan_interval: float = 1.0,
        random_source: Callable[[], float] = random.random,
    ) -> None:
        if scan_interval <= 0 or scan_interval > 60:
            raise ValueError("scan_interval must be between zero and 60 seconds")
        self._repository = repository
        self._ingress = ingress
        self._credentials = credential_store
        self._adapters = adapters
        self._registry = destination_registry
        self._network_factory = network_factory
        self._http_factory = http_factory
        self._scan_interval = scan_interval
        self._random = random_source
        self._managed: dict[str, _Managed] = {}
        self._diagnostics: dict[str, ConnectorSnapshot] = {}
        self._invalidated: set[str] = set()
        self._wake = asyncio.Event()

    async def run_forever(self) -> None:
        try:
            while True:
                await self.reconcile()
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=self._scan_interval)
                except asyncio.TimeoutError:
                    pass
        finally:
            await self.close()

    def wake(self) -> None:
        self._wake.set()

    def invalidate(self, account_id: str) -> None:
        """Force restart after in-place protected credential rotation."""
        self._invalidated.add(account_id)
        self._wake.set()

    async def reconcile(self) -> None:
        desired = self._desired_accounts()
        for account_id, managed in tuple(self._managed.items()):
            row = desired.get(account_id)
            if (
                row is None or row.get("credential_ref") != managed.credential_ref
                or account_id in self._invalidated
            ):
                await self._stop(account_id, managed)
        for account_id, row in desired.items():
            managed = self._managed.get(account_id)
            if managed is not None and not managed.task.done():
                self._diagnostics[account_id] = managed.connector.snapshot()
                continue
            if (
                managed is not None and managed.task.done()
                and managed.connector.snapshot().last_error == "ConnectorAuthenticationError"
            ):
                self._diagnostics[account_id] = managed.connector.snapshot()
                continue
            if managed is not None:
                await self._stop(account_id, managed)
            try:
                connector, adapter = self._build(row)
            except Exception as exc:
                self._diagnostics[account_id] = ConnectorSnapshot(
                    account_id, str(row["adapter_kind"]), state="configuration_error",
                    last_error=type(exc).__name__,
                )
                continue
            self._adapters[account_id] = adapter
            self._registry._adapters[account_id] = adapter
            task = asyncio.create_task(
                self._run_connector(connector), name=f"gateway-connector:{account_id}",
            )
            self._managed[account_id] = _Managed(str(row["credential_ref"]), task, connector)
            self._invalidated.discard(account_id)
            self._diagnostics[account_id] = connector.snapshot()

    async def close(self) -> None:
        for account_id, managed in tuple(self._managed.items()):
            await self._stop(account_id, managed)

    def snapshot(self, account_id: str) -> dict[str, Any]:
        managed = self._managed.get(account_id)
        value = managed.connector.snapshot() if managed else self._diagnostics.get(account_id)
        if value is None:
            return {
                "state": "not_managed", "authenticated": False,
                "session_resumable": False, "last_error": None,
            }
        return value.as_dict()

    def _desired_accounts(self) -> dict[str, dict[str, Any]]:
        rows = self._repository.control_plane._get_conn().execute(
            """SELECT * FROM channel_accounts
                 WHERE enabled=1 AND adapter_kind IN ('discord','dingtalk','qq','wecom')
                 ORDER BY account_id LIMIT 1000"""
        ).fetchall()
        return {
            str(row["account_id"]): self._repository._channel_account(row)
            for row in rows if row["credential_ref"]
        }

    def _build(self, row: dict[str, Any]) -> tuple[Any, Any]:
        account_id, kind = str(row["account_id"]), str(row["adapter_kind"])
        if kind not in CONNECTOR_KINDS:
            raise ValueError("unsupported connector account")
        secret = self._credentials.resolve_for_account(account_id, row["credential_ref"])
        credential = parse_connector_credential(kind, secret)
        network, http = self._network_factory(), self._http_factory()
        common = {
            "account_id": account_id, "ingress": self._ingress,
            "repository": self._repository, "network": network,
            "credential": credential,
        }
        if kind == "discord":
            adapter = DiscordAdapter(
                account_id=account_id, transport=http,
                bot_token=credential["bot_token"],
                application_id=credential["application_id"],
            )
            connector = DiscordGatewayConnector(adapter=adapter, http=http, **common)
        elif kind == "qq":
            adapter = QQAdapter(
                account_id=account_id, transport=http,
                access_token=credential["access_token"], app_id=credential["app_id"],
            )
            connector = QQGatewayConnector(adapter=adapter, http=http, **common)
        elif kind == "dingtalk":
            adapter = DingTalkAdapter(
                account_id=account_id, transport=http,
                access_token=credential["access_token"], robot_code=credential["robot_code"],
            )
            connector = DingTalkStreamConnector(adapter=adapter, http=http, **common)
        else:
            holder: dict[str, WeComAIBotConnector] = {}

            async def send_reply(request_id: str, content: str, delivery_key: str):
                return await holder["connector"].send_reply(request_id, content, delivery_key)

            adapter = WeComAdapter(
                account_id=account_id, bot_id=credential["bot_id"],
                gateway_sender=send_reply,
            )
            connector = WeComAIBotConnector(adapter=adapter, **common)
            holder["connector"] = connector
        return connector, adapter

    async def _run_connector(self, connector: Any) -> None:
        failures = 0
        while True:
            try:
                await connector.run_once()
                failures = 0
            except asyncio.CancelledError:
                raise
            except ConnectorAuthenticationError:
                self._diagnostics[connector.account_id] = connector.snapshot()
                return
            except Exception:
                failures += 1
            self._diagnostics[connector.account_id] = connector.snapshot()
            raw = min(30.0, 0.5 * (2 ** min(failures, 6)))
            delay = max(0.05, raw * (0.8 + self._random() * 0.4))
            await asyncio.sleep(delay)

    async def _stop(self, account_id: str, managed: _Managed) -> None:
        if self._managed.get(account_id) is managed:
            self._managed.pop(account_id, None)
        managed.task.cancel()
        await asyncio.gather(managed.task, return_exceptions=True)
        self._diagnostics[account_id] = replace(
            managed.connector.snapshot(), state="stopped", authenticated=False,
        )
        self._adapters.pop(account_id, None)
        self._registry._adapters.pop(account_id, None)


__all__ = ["CONNECTOR_KINDS", "ConnectorManager"]
