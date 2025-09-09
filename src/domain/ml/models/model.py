"""
Base Pydantic models for the API.
This module contains the base models used throughout the API.
"""

import json
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, ClassVar, Dict, Generic, List, Optional, Type, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

T = TypeVar("T")
M = TypeVar("M", bound="BaseDataModel")


class PydanticBaseModel(BaseModel):
    """Base model for all API models with common configuration."""

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=lambda field_name: "".join(
            word.capitalize() if i > 0 else word
            for i, word in enumerate(field_name.split("_"))
        ),
        validate_assignment=True,
        extra="forbid",
        json_schema_extra={"examples": []},
    )


class PageInfo(PydanticBaseModel):
    """Pagination information model."""

    page: int = Field(..., description="Current page number (1-indexed)", ge=1)
    page_size: int = Field(..., description="Items per page", ge=1, le=1000)
    total_items: int = Field(..., description="Total number of items", ge=0)
    total_pages: int = Field(..., description="Total number of pages", ge=0)

    @model_validator(mode="after")
    def validate_pagination_consistency(self) -> "PageInfo":
        """Validate pagination values are consistent."""
        expected_pages = (self.total_items + self.page_size - 1) // self.page_size
        if self.total_items > 0 and self.total_pages != expected_pages:
            raise ValueError(
                f"Inconsistent pagination: expected {expected_pages} pages"
            )

        if self.page > self.total_pages and self.total_pages > 0:
            raise ValueError("Page number exceeds total pages")

        return self


class ErrorDetail(PydanticBaseModel):
    """Detailed error information for API responses."""

    code: str = Field(..., description="Error code")
    message: str = Field(..., description="Error message")
    location: Optional[str] = Field(None, description="Error location")
    field: Optional[str] = Field(None, description="Field that caused error")


class ApiResponse(PydanticBaseModel, Generic[T]):
    """Generic API response wrapper for consistent structure."""

    success: bool = Field(True, description="Request success status")
    data: Optional[T] = Field(None, description="Response data")
    error: Optional[ErrorDetail] = Field(None, description="Error details")
    meta: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    trace_id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()))

    @model_validator(mode="after")
    def validate_response_consistency(self) -> "ApiResponse":
        """Validate response fields are consistent with success status."""
        if self.success and self.error is not None:
            raise ValueError("Error must be None when success is True")
        if not self.success and self.error is None:
            raise ValueError("Error must be provided when success is False")
        return self


class PaginatedResponse(PydanticBaseModel, Generic[T]):
    """Generic paginated response model."""

    data: List[T] = Field(default_factory=list, description="List of items")
    page_info: PageInfo = Field(..., description="Pagination information")


class BaseDataModel(ABC):
    """Base class for all data models with common functionality."""

    _fields: ClassVar[Dict[str, Type]] = {}
    _required_fields: ClassVar[List[str]] = []

    def __init__(self, **kwargs):
        """Initialize model with given attributes."""
        self._id = kwargs.pop("id", str(uuid.uuid4()))
        self._created_at = kwargs.pop("created_at", datetime.now())
        self._updated_at = kwargs.pop("updated_at", datetime.now())

        # Set provided attributes
        for key, value in kwargs.items():
            setattr(self, key, value)

        # Initialize missing fields
        for field in self._fields:
            if not hasattr(self, field):
                setattr(self, field, None)

    @property
    def id(self) -> str:
        """Model identifier."""
        return self._id

    @property
    def created_at(self) -> datetime:
        """Creation timestamp."""
        return self._created_at

    @property
    def updated_at(self) -> datetime:
        """Last update timestamp."""
        return self._updated_at

    def validate(self) -> bool:
        """Validate model against schema."""
        # Check required fields
        for field in self._required_fields:
            if not hasattr(self, field) or getattr(self, field) is None:
                raise ValueError(f"Required field '{field}' is missing")

        # Check field types
        for field, expected_type in self._fields.items():
            value = getattr(self, field, None)
            if value is not None and not isinstance(value, expected_type):
                raise TypeError(
                    f"Field '{field}' has incorrect type. "
                    f"Expected {expected_type}, got {type(value)}"
                )

        self._validate()
        return True

    @abstractmethod
    def _validate(self) -> None:
        """Custom validation logic implemented by subclasses."""
        pass

    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary."""
        result = {
            "id": self._id,
            "created_at": self._created_at.isoformat(),
            "updated_at": self._updated_at.isoformat(),
        }

        for field in self._fields:
            value = getattr(self, field, None)
            if isinstance(value, BaseDataModel):
                result[field] = value.to_dict()
            elif (
                isinstance(value, list)
                and value
                and isinstance(value[0], BaseDataModel)
            ):
                result[field] = [item.to_dict() for item in value]
            else:
                result[field] = value

        return result

    def to_json(self) -> str:
        """Convert model to JSON string."""
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls: Type[M], data: Dict[str, Any]) -> M:
        """Create model from dictionary."""
        # Handle datetime conversion
        for dt_field in ["created_at", "updated_at"]:
            if dt_field in data and isinstance(data[dt_field], str):
                data[dt_field] = datetime.fromisoformat(data[dt_field])

        return cls(**data)

    @classmethod
    def from_json(cls: Type[M], json_str: str) -> M:
        """Create model from JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id={self._id})"


# Type aliases for common response patterns
ListResponse = ApiResponse[List[T]]
ItemResponse = ApiResponse[T]
EmptyResponse = ApiResponse[None]
