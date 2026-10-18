from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AISelection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    provider_id: str = Field(min_length=1, max_length=32)
    model: str = Field(min_length=1, max_length=200)


Modality = Literal["text", "image", "audio", "video", "file"]


class AIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=200)
    max_input_tokens: int | None = Field(None, ge=1, le=1_000_000_000)
    max_output_tokens: int | None = Field(None, ge=1, le=1_000_000_000)
    input_types: list[Modality] = Field(default_factory=lambda: ["text"], min_length=1, max_length=5)
    output_types: list[Modality] = Field(default_factory=lambda: ["text"], min_length=1, max_length=5)

    @field_validator("input_types", "output_types")
    @classmethod
    def unique_types(cls, values):
        return list(dict.fromkeys(values))


class ProviderInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    base_url: str = Field(min_length=1, max_length=2000)
    api_key: str | None = Field(None, max_length=2000)
    models: list[AIModel] = Field(default_factory=list, max_length=100)
    timeout: int = Field(20, ge=5, le=120)
    concurrency: int = Field(2, ge=1, le=10)

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value):
        value = value.rstrip("/")
        url = urlparse(value)
        if (
            url.scheme not in {"http", "https"} or not url.hostname
            or url.username or url.password or url.query or url.fragment
        ):
            raise ValueError("需要不含凭据的 HTTP(S) API 地址")
        return value

    @field_validator("models")
    @classmethod
    def valid_models(cls, values):
        if len({model.id for model in values}) != len(values):
            raise ValueError("模型 ID 不能重复")
        return values


class Provider(ProviderInput):
    id: str

    @field_validator("models", mode="before")
    @classmethod
    def migrate_model_ids(cls, values):
        # Existing saved catalogues predate per-model capability settings.
        return [dict(id=value, input_types=["text", "image"], output_types=["text"])
                if isinstance(value, str) else value for value in values]


class PublicProvider(BaseModel):
    id: str
    name: str
    base_url: str
    has_api_key: bool
    models: list[AIModel]
    timeout: int
    concurrency: int


@dataclass(frozen=True)
class AIRequestConfig:
    provider_id: str
    base_url: str
    api_key: str | None
    model: str
    timeout: int = 20
    concurrency: int = 2
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    input_types: tuple[Modality, ...] = ("text", "image")
    output_types: tuple[Modality, ...] = ("text",)
