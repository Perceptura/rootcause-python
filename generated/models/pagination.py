from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset






T = TypeVar("T", bound="Pagination")



@_attrs_define
class Pagination:
    """ 
        Attributes:
            cursor (str | Unset):
            has_more (bool | Unset):
            total (int | Unset):
     """

    cursor: str | Unset = UNSET
    has_more: bool | Unset = UNSET
    total: int | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        cursor = self.cursor

        has_more = self.has_more

        total = self.total


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
        })
        if cursor is not UNSET:
            field_dict["cursor"] = cursor
        if has_more is not UNSET:
            field_dict["hasMore"] = has_more
        if total is not UNSET:
            field_dict["total"] = total

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        cursor = d.pop("cursor", UNSET)

        has_more = d.pop("hasMore", UNSET)

        total = d.pop("total", UNSET)

        pagination = cls(
            cursor=cursor,
            has_more=has_more,
            total=total,
        )


        pagination.additional_properties = d
        return pagination

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
