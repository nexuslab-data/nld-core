import datetime
import uuid
from typing import Literal, cast

from nld.flow.exceptions import (
    InvalidFlowRequestParametersException,
)
from nld.flow.utils import FlowLoadingStrategies
from nld.pydantic import NldBaseModel
from nld.utils import NldStrEnum
from nld.utils.datetime_util import (
    COMPACT_DATETIME_FORMAT,
    get_current_datetime,
    normalize_to_utc,
)

# TODO: Check if the requests should be kept


class FlowRequestStatus(NldStrEnum):
    PLANNED = "PLANNED"
    CANCELLED = "CANCELLED"
    ONGOING = "ONGOING"


FLOW_REQUEST_STATUS_LITERAL = Literal["PLANNED", "CANCELLED", "ONGOING"]


class FlowRequestType(NldStrEnum):
    FIXED_RANGE_TST = "FIXED_RANGE_TST"
    FIXED_RANGE = "FIXED_RANGE"
    FUNCTIONAL_KEY = "FUNC_KEY"
    FULL = "FULL"


FLOW_REQUEST_TYPE_LITERAL = Literal[
    "FIXED_RANGE_TST", "FIXED_RANGE", "FUNC_KEY", "FULL"
]


class FlowRequest(NldBaseModel):
    request_uid: str
    flow_namespace: str
    flow_name: str
    flow_instance_name: str
    request_type: str
    flow_loading_strategy: str
    run_status: FLOW_REQUEST_STATUS_LITERAL
    requestor_name: str | None = None
    request_description: str | None = None
    pull_from: datetime.datetime | None = None
    pull_to: datetime.datetime | None = None
    pull_filter: str | None = None
    load_from: datetime.datetime | None = None
    load_to: datetime.datetime | None = None
    load_filter: str | None = None
    functional_key: str | None = None
    delta_period_range_from_type: str | None = None
    delta_period_range_from: str | None = None
    delta_period_range_to_type: str | None = None
    delta_period_range_to: str | None = None

    @classmethod
    def generate_uuid(cls) -> str:
        return uuid.uuid4().__str__()

    @classmethod
    def create_fixed_range_tst_timestamp_on_pull_request_to_plan(
        cls,
        flow_namespace: str,
        flow_name: str,
        flow_instance_name: str,
        request_description: str | None = None,
        requestor_name: str | None = None,
        flow_loading_strategy: str | None = None,
        pull_from: datetime.datetime | None = None,
        pull_to: datetime.datetime | None = None,
        pull_filter: str | None = None,
    ) -> "FlowRequest":
        cls.check_flow_loading_strategy_valid_for_request(flow_loading_strategy)
        flow_loading_strategy = cast(str, flow_loading_strategy)

        pull_from = normalize_to_utc(pull_from)
        pull_to = normalize_to_utc(pull_to)

        if flow_loading_strategy == FlowLoadingStrategies.BACKFILL_DELTA:
            if pull_from is None:
                raise InvalidFlowRequestParametersException(
                    flow_namespace,
                    flow_name,
                    flow_instance_name,
                    "Fixed Range Timestamp - Backfill Delta - "
                    "Pull from is mandatory and was not provided",
                )
            if pull_from > get_current_datetime():
                raise InvalidFlowRequestParametersException(
                    flow_namespace,
                    flow_name,
                    flow_instance_name,
                    "Fixed Range Timestamp - Backfill Delta - "
                    "Pull from should be prior to current timestamp - From: "
                    + pull_from.strftime(COMPACT_DATETIME_FORMAT),
                )
        if flow_loading_strategy == FlowLoadingStrategies.BACKFILL:
            if pull_from is None:
                raise InvalidFlowRequestParametersException(
                    flow_namespace,
                    flow_name,
                    flow_instance_name,
                    "Fixed Range Timestamp - Backfill - "
                    "Pull from is mandatory and was not provided",
                )
            if pull_to is None:
                raise InvalidFlowRequestParametersException(
                    flow_namespace,
                    flow_name,
                    flow_instance_name,
                    "Fixed Range Timestamp - Backfill - "
                    "Pull to is mandatory and was not provided",
                )
            if pull_from > pull_to:
                raise InvalidFlowRequestParametersException(
                    flow_namespace,
                    flow_name,
                    flow_instance_name,
                    "Fixed Range Timestamp - Backfill - "
                    "Pull from should be prior to pull to - From: "
                    + pull_from.strftime(COMPACT_DATETIME_FORMAT)
                    + " / To: "
                    + pull_to.strftime(COMPACT_DATETIME_FORMAT),
                )

        return FlowRequest(
            request_uid=cls.generate_uuid(),
            flow_namespace=flow_namespace,
            flow_name=flow_name,
            flow_instance_name=flow_instance_name,
            request_description=request_description,
            request_type=FlowRequestType.FIXED_RANGE_TST.value,
            requestor_name=requestor_name,
            flow_loading_strategy=flow_loading_strategy,
            run_status=FlowRequestStatus.PLANNED.value,
            pull_from=pull_from,
            pull_to=pull_to,
            pull_filter=pull_filter,
        )

    @classmethod
    def create_fixed_range_timestamp_on_pull_request_to_plan(
        cls,
        flow_namespace: str,
        flow_name: str,
        flow_instance_name: str,
        request_description: str | None = None,
        requestor_name: str | None = None,
        flow_loading_strategy: str | None = None,
        delta_period_range_from_type: str | None = None,
        delta_period_range_from: str | None = None,
        delta_period_range_to_type: str | None = None,
        delta_period_range_to: str | None = None,
    ) -> "FlowRequest":
        cls.check_flow_loading_strategy_valid_for_request(flow_loading_strategy)
        flow_loading_strategy = cast(str, flow_loading_strategy)
        if flow_loading_strategy == FlowLoadingStrategies.BACKFILL_DELTA:
            if delta_period_range_from_type is None or delta_period_range_from is None:
                raise InvalidFlowRequestParametersException(
                    flow_namespace,
                    flow_name,
                    flow_instance_name,
                    "Fixed Range - Backfill Delta - "
                    "Period Range From Type and Value are mandatory",
                )
        if flow_loading_strategy == FlowLoadingStrategies.BACKFILL:
            if delta_period_range_from_type is None or delta_period_range_from is None:
                raise InvalidFlowRequestParametersException(
                    flow_namespace,
                    flow_name,
                    flow_instance_name,
                    "Fixed Range - Backfill - "
                    "Period Range From Type and Value are mandatory",
                )
            if delta_period_range_to_type is None or delta_period_range_to is None:
                raise InvalidFlowRequestParametersException(
                    flow_namespace,
                    flow_name,
                    flow_instance_name,
                    "Fixed Range - Backfill - "
                    "Period Range To Type and Value are mandatory",
                )

        return FlowRequest(
            request_uid=cls.generate_uuid(),
            flow_namespace=flow_namespace,
            flow_name=flow_name,
            flow_instance_name=flow_instance_name,
            request_description=request_description,
            request_type=FlowRequestType.FIXED_RANGE.value,
            requestor_name=requestor_name,
            flow_loading_strategy=flow_loading_strategy,
            run_status=FlowRequestStatus.PLANNED.value,
            delta_period_range_from_type=delta_period_range_from_type,
            delta_period_range_from=delta_period_range_from,
            delta_period_range_to_type=delta_period_range_to_type,
            delta_period_range_to=delta_period_range_to,
        )

    @classmethod
    def create_target_functional_key_request_to_plan(
        cls,
        flow_namespace: str,
        flow_name: str,
        flow_instance_name: str,
        request_description: str | None = None,
        requestor_name: str | None = None,
        flow_loading_strategy: str | None = None,
        functional_key: str | None = None,
    ) -> "FlowRequest":
        cls.check_flow_loading_strategy_valid_for_request(flow_loading_strategy)
        flow_loading_strategy = cast(str, flow_loading_strategy)
        if functional_key is None:
            raise InvalidFlowRequestParametersException(
                flow_namespace,
                flow_name,
                flow_instance_name,
                "Functional Key - Backfill Delta - "
                "Functional Key information is mandatory",
            )

        return FlowRequest(
            request_uid=cls.generate_uuid(),
            flow_namespace=flow_namespace,
            flow_name=flow_name,
            flow_instance_name=flow_instance_name,
            request_description=request_description,
            request_type=FlowRequestType.FUNCTIONAL_KEY.value,
            requestor_name=requestor_name,
            flow_loading_strategy=flow_loading_strategy,
            run_status=FlowRequestStatus.PLANNED.value,
            functional_key=functional_key,
        )

    @classmethod
    def check_flow_loading_strategy_valid_for_request(
        cls, flow_loading_strategy: str | None
    ) -> None:
        if flow_loading_strategy is None:
            raise ValueError("Flow Loading Strategy requires a loading strategy")
        if flow_loading_strategy not in [
            FlowLoadingStrategies.BACKFILL.value,
            FlowLoadingStrategies.BACKFILL_DELTA.value,
        ]:
            raise ValueError(
                "Flow Loading Strategy for a request is expected to be one of "
                "the values: "
                + ",".join(
                    [
                        FlowLoadingStrategies.BACKFILL.value,
                        FlowLoadingStrategies.BACKFILL_DELTA.value,
                    ]
                )
            )
