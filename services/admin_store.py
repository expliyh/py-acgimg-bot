"""In-memory administration store for managing dashboard data."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
from uuid import uuid4


@dataclass
class Group:
    id: str
    name: str
    description: str = ""
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    tags: List[str] = field(default_factory=list)


@dataclass
class PrivateChat:
    id: str
    username: str
    alias: Optional[str] = None
    is_muted: bool = False
    last_message_preview: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class FeatureConfig:
    id: str
    name: str
    enabled: bool = True
    description: str = ""
    options: Dict[str, str] = field(default_factory=dict)


@dataclass
class AutomationRule:
    id: str
    name: str
    trigger: str
    action: str
    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)


class AdminStore:
    """Thread-safe in-memory data store."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._groups: Dict[str, Group] = {}
        self._private_chats: Dict[str, PrivateChat] = {}
        self._feature_configs: Dict[str, FeatureConfig] = {}
        self._automation_rules: Dict[str, AutomationRule] = {}

    async def list_groups(self) -> List[Group]:
        async with self._lock:
            return list(self._groups.values())

    async def create_group(self, name: str, description: str, tags: Optional[List[str]] = None) -> Group:
        async with self._lock:
            group_id = uuid4().hex
            group = Group(id=group_id, name=name, description=description, tags=tags or [])
            self._groups[group_id] = group
            return group

    async def update_group(self, group_id: str, **payload: object) -> Group:
        async with self._lock:
            if group_id not in self._groups:
                raise KeyError("Group not found")
            group = self._groups[group_id]
            for key, value in payload.items():
                if hasattr(group, key) and value is not None:
                    setattr(group, key, value)
            return group

    async def delete_group(self, group_id: str) -> None:
        async with self._lock:
            if group_id not in self._groups:
                raise KeyError("Group not found")
            del self._groups[group_id]

    async def list_private_chats(self) -> List[PrivateChat]:
        async with self._lock:
            return list(self._private_chats.values())

    async def create_private_chat(self, username: str, alias: Optional[str] = None) -> PrivateChat:
        async with self._lock:
            chat_id = uuid4().hex
            chat = PrivateChat(id=chat_id, username=username, alias=alias)
            self._private_chats[chat_id] = chat
            return chat

    async def update_private_chat(self, chat_id: str, **payload: object) -> PrivateChat:
        async with self._lock:
            if chat_id not in self._private_chats:
                raise KeyError("Private chat not found")
            chat = self._private_chats[chat_id]
            for key, value in payload.items():
                if hasattr(chat, key) and value is not None:
                    setattr(chat, key, value)
            return chat

    async def delete_private_chat(self, chat_id: str) -> None:
        async with self._lock:
            if chat_id not in self._private_chats:
                raise KeyError("Private chat not found")
            del self._private_chats[chat_id]

    async def list_feature_configs(self) -> List[FeatureConfig]:
        async with self._lock:
            return list(self._feature_configs.values())

    async def upsert_feature_config(
        self,
        name: str,
        enabled: Optional[bool] = None,
        description: Optional[str] = None,
        options: Optional[Dict[str, str]] = None,
    ) -> FeatureConfig:
        async with self._lock:
            found = next((cfg for cfg in self._feature_configs.values() if cfg.name == name), None)
            if found is None:
                cfg_id = uuid4().hex
                found = FeatureConfig(
                    id=cfg_id,
                    name=name,
                    enabled=True if enabled is None else enabled,
                    description=description or "",
                    options=options or {},
                )
                self._feature_configs[cfg_id] = found
            else:
                if enabled is not None:
                    found.enabled = enabled
                if description is not None:
                    found.description = description
                if options is not None:
                    found.options = options
            return found

    async def delete_feature_config(self, config_id: str) -> None:
        async with self._lock:
            if config_id not in self._feature_configs:
                raise KeyError("Feature config not found")
            del self._feature_configs[config_id]

    async def list_automation_rules(self) -> List[AutomationRule]:
        async with self._lock:
            return list(self._automation_rules.values())

    async def create_automation_rule(
        self,
        name: str,
        trigger: str,
        action: str,
        enabled: bool = True,
    ) -> AutomationRule:
        async with self._lock:
            rule_id = uuid4().hex
            rule = AutomationRule(id=rule_id, name=name, trigger=trigger, action=action, enabled=enabled)
            self._automation_rules[rule_id] = rule
            return rule

    async def update_automation_rule(self, rule_id: str, **payload: object) -> AutomationRule:
        async with self._lock:
            if rule_id not in self._automation_rules:
                raise KeyError("Automation rule not found")
            rule = self._automation_rules[rule_id]
            for key, value in payload.items():
                if hasattr(rule, key) and value is not None:
                    setattr(rule, key, value)
            return rule

    async def delete_automation_rule(self, rule_id: str) -> None:
        async with self._lock:
            if rule_id not in self._automation_rules:
                raise KeyError("Automation rule not found")
            del self._automation_rules[rule_id]

    async def dashboard_snapshot(self) -> Dict[str, object]:
        async with self._lock:
            active_groups = sum(1 for group in self._groups.values() if group.is_active)
            muted_chats = sum(1 for chat in self._private_chats.values() if chat.is_muted)
            return {
                "groups": len(self._groups),
                "active_groups": active_groups,
                "private_chats": len(self._private_chats),
                "muted_chats": muted_chats,
                "automations": len(self._automation_rules),
            }
