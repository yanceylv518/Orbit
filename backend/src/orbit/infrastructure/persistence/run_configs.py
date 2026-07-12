from __future__ import annotations

from copy import deepcopy
from typing import Any


class InMemoryRunConfigRepository:
    def __init__(self, configs: list[dict[str, Any]], app_config: dict[str, Any]):
        self.configs = configs
        self.app_config = app_config
        self._sync_config_reference()

    def all(self) -> list[dict[str, Any]]:
        return self.configs

    def get(self, account_id: str) -> dict[str, Any] | None:
        return next((config for config in self.configs if config.get("account_id") == account_id), None)

    def save(self, config: dict[str, Any]) -> dict[str, Any]:
        account_id = str(config["account_id"])
        existing = self.get(account_id)
        if existing is None:
            self.configs.append(config)
            self._sync_config_reference()
            return config
        if existing is not config:
            existing.clear()
            existing.update(config)
        self._sync_config_reference()
        return existing

    def replace_all(self, configs: list[dict[str, Any]]) -> None:
        if configs is not self.configs:
            self.configs.clear()
            self.configs.extend(configs)
        self._sync_config_reference()

    def snapshot(self) -> list[dict[str, Any]]:
        return deepcopy(self.configs)

    def restore(self, configs: list[dict[str, Any]]) -> None:
        self.replace_all(deepcopy(configs))

    def _sync_config_reference(self) -> None:
        self.app_config["account_run_configs"] = self.configs
