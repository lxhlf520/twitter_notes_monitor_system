from __future__ import annotations

from typing import TYPE_CHECKING, Dict

from ..utils import flatten_params, get_query_id

import logging
logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    # from ..guest.client import GuestClient
    from .client import Client

    ClientType = Client



class GQLClient:
    def __init__(self, base: ClientType) -> None:
        self.base = base

    def gql_get(
        self,
        endpoint: str,
        params: Dict | None = None,
        headers: Dict | None = None,
        **kwargs
    ):
        if endpoint not in self.base.endpoint_params:
            logger.warning(f"Endpoint '{endpoint}' 不在 endpoint_params 中（JS 提取不完整），跳过")
            return {}, None
        endpoint_export = self.base.endpoint_params[endpoint]
        endpoint_url = endpoint_export["endpoint"]
        params.update(endpoint_export["params"])
        headers = self.base._base_headers
        return self.base.get(endpoint_url, params=flatten_params(params), headers=headers, **kwargs)
        
    def gql_post(
        self,
        endpoint: str,
        params: Dict | None = None,
        headers: dict | None = None,
        **kwargs
    ):
        if endpoint not in self.base.endpoint_params:
            logger.warning(f"Endpoint '{endpoint}' 不在 endpoint_params 中（JS 提取不完整），跳过")
            return {}, None
        endpoint_export = self.base.endpoint_params[endpoint]
        endpoint_url = endpoint_export["endpoint"]
        params.update(endpoint_export["params"])
        headers = self.base._base_headers
        return self.base.post(endpoint_url, json=params, headers=headers, **kwargs)

    def tweet_detail(self, tweet_id, cursor):
        variables = {
            'focalTweetId': tweet_id,
            'with_rux_injections': False,
            'includePromotedContent': True,
            'withCommunity': True,
            'withQuickPromoteEligibilityTweetFields': True,
            'withBirdwatchNotes': True,
            'withVoice': True,
            'withV2Timeline': True
        }
        if cursor is not None:
            variables['cursor'] = cursor
        params = {
            "variables": variables
        }
        return self.gql_get('TweetDetail', params)

    def generic_timeline(self, timelineId):
        # timelineId = "VGltZWxpbmU6CwA6AAAAEzE4NTA3NzkwMTg4NDY3MzYzODQA"
        variables = {"timelineId":timelineId,"count":20,"withQuickPromoteEligibilityTweetFields":True}
        params = {
            "variables": variables
        }
        return self.gql_get('GenericTimelineById', params)
    
    def birdwatch_fetch_global_timeline(self):
        variables = {}
        params = {
            "variables": variables
        }
        return self.gql_get('BirdwatchFetchGlobalTimeline', params)
    
    def birdwatch_fetch_notes(self, tweet_id: str):
        variables = {"tweet_id":tweet_id}
        params = {
            "variables": variables
        }
        return self.gql_get('BirdwatchFetchNotes', params)