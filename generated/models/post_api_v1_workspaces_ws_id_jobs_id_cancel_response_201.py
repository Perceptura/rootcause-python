from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast

if TYPE_CHECKING:
  from ..models.post_api_v1_workspaces_ws_id_jobs_id_cancel_response_201_data import PostApiV1WorkspacesWsIdJobsIdCancelResponse201Data





T = TypeVar("T", bound="PostApiV1WorkspacesWsIdJobsIdCancelResponse201")



@_attrs_define
class PostApiV1WorkspacesWsIdJobsIdCancelResponse201:
    """ 
        Attributes:
            data (PostApiV1WorkspacesWsIdJobsIdCancelResponse201Data | Unset):
     """

    data: PostApiV1WorkspacesWsIdJobsIdCancelResponse201Data | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.post_api_v1_workspaces_ws_id_jobs_id_cancel_response_201_data import PostApiV1WorkspacesWsIdJobsIdCancelResponse201Data
        data: dict[str, Any] | Unset = UNSET
        if not isinstance(self.data, Unset):
            data = self.data.to_dict()


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
        })
        if data is not UNSET:
            field_dict["data"] = data

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.post_api_v1_workspaces_ws_id_jobs_id_cancel_response_201_data import PostApiV1WorkspacesWsIdJobsIdCancelResponse201Data
        d = dict(src_dict)
        _data = d.pop("data", UNSET)
        data: PostApiV1WorkspacesWsIdJobsIdCancelResponse201Data | Unset
        if isinstance(_data,  Unset):
            data = UNSET
        else:
            data = PostApiV1WorkspacesWsIdJobsIdCancelResponse201Data.from_dict(_data)




        post_api_v1_workspaces_ws_id_jobs_id_cancel_response_201 = cls(
            data=data,
        )


        post_api_v1_workspaces_ws_id_jobs_id_cancel_response_201.additional_properties = d
        return post_api_v1_workspaces_ws_id_jobs_id_cancel_response_201

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
