from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Dict, Literal

from .utils import timestamp_to_datetime

if TYPE_CHECKING:
    # from httpx import Response

    from .client.client import Client
    # from .message import Message
    from .tweet import Tweet
    from .utils import Result


class User:
    """
    Attributes
    ----------
    id : :class:`str`
        The unique identifier of the user.
    created_at : :class:`str`
        The date and time when the user account was created.
    name : :class:`str`
        The user's name.
    screen_name : :class:`str`
        The user's screen name.
    profile_image_url : :class:`str`
        The URL of the user's profile image (HTTPS version).
    profile_banner_url : :class:`str`
        The URL of the user's profile banner.
    url : :class:`str`
        The user's URL.
    location : :class:`str`
        The user's location information.
    description : :class:`str`
        The user's profile description.
    description_urls : :class:`list`
        URLs found in the user's profile description.
    urls : :class:`list`
        URLs associated with the user.
    pinned_tweet_ids : :class:`str`
        The IDs of tweets that the user has pinned to their profile.
    is_blue_verified : :class:`bool`
        Indicates if the user is verified with a blue checkmark.
    verified : :class:`bool`
        Indicates if the user is verified.
    possibly_sensitive : :class:`bool`
        Indicates if the user's content may be sensitive.
    can_dm : :class:`bool`
        Indicates whether the user can receive direct messages.
    can_media_tag : :class:`bool`
        Indicates whether the user can be tagged in media.
    want_retweets : :class:`bool`
        Indicates if the user wants retweets.
    default_profile : :class:`bool`
        Indicates if the user has the default profile.
    default_profile_image : :class:`bool`
        Indicates if the user has the default profile image.
    has_custom_timelines : :class:`bool`
        Indicates if the user has custom timelines.
    followers_count : :class:`int`
        The count of followers.
    fast_followers_count : :class:`int`
        The count of fast followers.
    normal_followers_count : :class:`int`
        The count of normal followers.
    following_count : :class:`int`
        The count of users the user is following.
    favourites_count : :class:`int`
        The count of favorites or likes.
    listed_count : :class:`int`
        The count of lists the user is a member of.
    media_count : :class:`int`
        The count of media items associated with the user.
    statuses_count : :class:`int`
        The count of tweets.
    is_translator : :class:`bool`
        Indicates if the user is a translator.
    translator_type : :class:`str`
        The type of translator.
    profile_interstitial_type : :class:`str`
        The type of profile interstitial.
    withheld_in_countries : list[:class:`str`]
        Countries where the user's content is withheld.
    """

    def __init__(self, client: 'Client' = None, data: Dict = None) -> None:
        self._client = client
        self.data = data
        self.legacy = data.get('legacy', {})
        self.core = data.get('core', {})
        self.location_info = data.get('location', {})
       
    
    @property
    def id(self) -> str:
        return self.data.get('rest_id', '')

    @property
    def translator_type(self) -> str:
        return self.legacy.get('translator_type', '')
    
    @property
    def protected(self) -> bool:
        return self.privacy.get('protected', False)
    
    @property
    def typename(self) -> str:
        return self.data.get('__typename', '')

    @property
    def created_at(self) -> str:
        created_at_str = self.core.get('created_at', '')
        if created_at_str:
            try:
                dt = datetime.strptime(created_at_str, '%a %b %d %H:%M:%S %z %Y')
                return dt.strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                pass
        return ''

    @property
    def name(self) -> str:
        return self.core.get('name', '')

    @property
    def screen_name(self) -> str:
        return self.core.get('screen_name', '')

    @property
    def avatar_url(self) -> str:
        return self.data.get('avatar', {}).get('image_url', '')

    @property
    def can_dm(self) -> bool:
        return self.dm_permissions.get('can_dm', False)

    @property
    def can_media_tag(self) -> bool:
        return self.media_permissions.get('can_media_tag', False)

    @property
    def protected(self) -> bool:
        return self.privacy.get('protected', False)

    @property
    def location(self) -> str:
        # 优先legacy中的location，否则用location字段
        return self.location_info.get('location', '')

    @property
    def description(self) -> str:
        return self.legacy.get('description', '')

    @property
    def description_urls(self) -> list:
        return self.legacy.get('entities', {}).get('description', {}).get('urls', [])

    @property
    def urls(self) -> list:
        return self.legacy.get('entities', {}).get('url', {}).get('urls', [])

    @property
    def pinned_tweet_ids(self) -> list:
        return self.legacy.get('pinned_tweet_ids_str', [])

    @property
    def is_blue_verified(self) -> bool:
        return self.data.get('is_blue_verified', False)

    @property
    def verified(self) -> str:
        if self.data.get("verification", {}).get("verified_type","") == "Business":
            return "gold"
        elif self.data.get("is_blue_verified", False):
            return "blue"
        else:
            return "none"

    @property
    def possibly_sensitive(self) -> bool:
        return self.legacy.get('possibly_sensitive', False)

    @property
    def default_profile(self) -> bool:
        return self.legacy.get('default_profile', False)

    @property
    def default_profile_image(self) -> bool:
        return self.legacy.get('default_profile_image', False)

    @property
    def has_custom_timelines(self) -> bool:
        return self.legacy.get('has_custom_timelines', False)

    @property
    def followers_count(self) -> int:
        return self.legacy.get('followers_count', 0)

    @property
    def fast_followers_count(self) -> int:
        return self.legacy.get('fast_followers_count', 0)

    @property
    def normal_followers_count(self) -> int:
        return self.legacy.get('normal_followers_count', 0)

    @property
    def following_count(self) -> int:
        return self.legacy.get('friends_count', 0)

    @property
    def favourites_count(self) -> int:
        return self.legacy.get('favourites_count', 0)

    @property
    def listed_count(self) -> int:
        return self.legacy.get('listed_count', 0)

    @property
    def media_count(self) -> int:
        return self.legacy.get('media_count', 0)

    @property
    def statuses_count(self) -> int:
        return self.legacy.get('statuses_count', 0)

    @property
    def is_translator(self) -> bool:
        return self.legacy.get('is_translator', False)

    @property
    def translator_type(self) -> str:
        return self.legacy.get('translator_type', '')

    @property
    def profile_interstitial_type(self) -> str:
        return self.legacy.get('profile_interstitial_type', '')

    @property
    def withheld_in_countries(self) -> list:
        return self.legacy.get('withheld_in_countries', [])

    @property
    def profile_image_url(self) -> str:
        return self.legacy.get('profile_image_url_https', '') or self.data.get('avatar', {}).get('image_url', '')

    @property
    def profile_banner_url(self) -> str:
        return self.legacy.get('profile_banner_url', '') or self.data.get('profile_banner_url', '')

    @property
    def url(self) -> str:
        return self.legacy.get('url', '')

    @property
    def want_retweets(self) -> bool:
        return self.legacy.get('want_retweets', False)

    @property
    def has_hidden_likes_on_profile(self) -> bool:
        return self.data.get('has_hidden_likes_on_profile', False)

    @property
    def has_hidden_subscriptions_on_profile(self) -> bool:
        return self.data.get('has_hidden_subscriptions_on_profile', False)

    @property
    def profile_image_shape(self) -> str:
        return self.data.get('profile_image_shape', '')

    @property
    def parody_commentary_fan_label(self) -> str:
        return self.data.get('parody_commentary_fan_label', '')

    @property
    def is_profile_translatable(self) -> bool:
        return self.data.get('is_profile_translatable', False)

    @property
    def has_graduated_access(self) -> bool:
        return self.data.get('has_graduated_access', False)

    @property
    def user_seed_tweet_count(self) -> int:
        return self.data.get('user_seed_tweet_count', 0)

    @property
    def premium_gifting_eligible(self) -> bool:
        return self.data.get('premium_gifting_eligible', False)

    @property
    def creator_subscriptions_count(self) -> int:
        return self.data.get('creator_subscriptions_count', 0)

    @property
    def affiliates_highlighted_label(self) -> dict:
        return self.data.get('affiliates_highlighted_label', {})

    @property
    def highlights_info(self) -> dict:
        return self.data.get('highlights_info', {})

    @property
    def tipjar_settings(self) -> dict:
        return self.data.get('tipjar_settings', {})

    @property
    def business_account(self) -> dict:
        return self.data.get('business_account', {})

    @property
    def legacy_extended_profile(self) -> dict:
        return self.data.get('legacy_extended_profile', {})

    @property
    def verification_info(self) -> dict:
        return self.data.get('verification_info', {})

    @property
    def relationship_perspectives(self) -> dict:
        return self.data.get('relationship_perspectives', {})

    @property
    def follow_request_sent(self) -> bool:
        """是否已发送关注请求"""
        return self.legacy.get('follow_request_sent', False)

    @property
    def notifications(self) -> bool:
        """是否开启通知"""
        return self.legacy.get('notifications', False)

    @property
    def pinned_tweet_ids_str(self) -> list:
        """置顶推文 ID 列表（字符串格式）"""
        return self.legacy.get('pinned_tweet_ids_str', [])

    @property
    def profile_image_url_https(self) -> str:
        """HTTPS 版本的 profile 图片 URL"""
        return self.legacy.get('profile_image_url_https', '')

    @property
    def entities(self) -> dict:
        """用户实体信息（包含 description 等）"""
        return self.legacy.get('entities', {})

    @property
    def has_hidden_likes(self) -> bool:
        """是否隐藏了点赞"""
        return self.data.get('has_hidden_likes', False)

    @property
    def has_hidden_subscriptions(self) -> bool:
        """是否隐藏了订阅"""
        return self.data.get('has_hidden_subscriptions', False)

    # @property
    # def user_info(self) -> dict:
    #     """
    #     获取用户所有信息的字典表示
    #     """
    #     return {
    #         "user_id": self.id,
    #         "created_at": self.created_at,
    #         "name": self.name,
    #         "username": self.screen_name,
    #         "url": f"https://x.com/{self.screen_name}",
    #         "web": self.url,
    #         "location": self.location,
    #         "description": self.description,
    #         "follower_count": self.followers_count,
    #         "following_count": self.following_count,
    #         "like_count": self.listed_count,
    #         "media_count": self.media_count,
    #         "statuses_count": self.statuses_count,
    #     }
    
    def get_tweets(
        self,
        tweet_type: Literal['Tweets', 'Replies', 'Media', 'Likes'],
        count: int = 40,
    ) -> Result[Tweet]:
        """
        Retrieves the user's tweets.

        Parameters
        ----------
        tweet_type : {'Tweets', 'Replies', 'Media', 'Likes'}
            The type of tweets to retrieve.
        count : :class:`int`, default=40
            The number of tweets to retrieve.

        Returns
        -------
        Result[:class:`Tweet`]
            A Result object containing a list of `Tweet` objects.

        Examples
        --------
        >>> user = client.get_user_by_screen_name('example_user')
        >>> tweets = user.get_tweets('Tweets', count=20)
        >>> for tweet in tweets:
        ...    print(tweet)
        <Tweet id="...">
        <Tweet id="...">
        ...
        ...

        >>> more_tweets = tweets.next()  # Retrieve more tweets
        >>> for tweet in more_tweets:
        ...     print(tweet)
        <Tweet id="...">
        <Tweet id="...">
        ...
        ...
        """
        return self._client.get_user_tweets(self.id, tweet_type, count)

    def follow(self) -> Response:
        """
        Follows the user.

        Returns
        -------
        :class:`httpx.Response`
            Response returned from twitter api.

        See Also
        --------
        Client.follow_user
        """
        return self._client.follow_user(self.id)

    def unfollow(self) -> Response:
        """
        Unfollows the user.

        Returns
        -------
        :class:`httpx.Response`
            Response returned from twitter api.

        See Also
        --------
        Client.unfollow_user
        """
        return self._client.unfollow_user(self.id)

    def block(self) -> Response:
        """
        Blocks a user.

        Parameters
        ----------
        user_id : :class:`str`
            The ID of the user to block.

        Returns
        -------
        :class:`httpx.Response`
            Response returned from twitter api.

        See Also
        --------
        .unblock
        """
        return self._client.block_user(self.id)

    def unblock(self) -> Response:
        """
        Unblocks a user.

        Parameters
        ----------
        user_id : :class:`str`
            The ID of the user to unblock.

        Returns
        -------
        :class:`httpx.Response`
            Response returned from twitter api.

        See Also
        --------
        .block
        """
        return self._client.unblock_user(self.id)

    def mute(self) -> Response:
        """
        Mutes a user.

        Parameters
        ----------
        user_id : :class:`str`
            The ID of the user to mute.

        Returns
        -------
        :class:`httpx.Response`
            Response returned from twitter api.

        See Also
        --------
        .unmute
        """
        return self._client.mute_user(self.id)

    def unmute(self) -> Response:
        """
        Unmutes a user.

        Parameters
        ----------
        user_id : :class:`str`
            The ID of the user to unmute.

        Returns
        -------
        :class:`httpx.Response`
            Response returned from twitter api.

        See Also
        --------
        .mute
        """
        return self._client.unmute_user(self.id)

    def get_followers(self, count: int = 20) -> Result[User]:
        """
        Retrieves a list of followers for the user.

        Parameters
        ----------
        count : :class:`int`, default=20
            The number of followers to retrieve.

        Returns
        -------
        Result[:class:`User`]
            A list of User objects representing the followers.

        See Also
        --------
        Client.get_user_followers
        """
        return self._client.get_user_followers(self.id, count)

    def get_verified_followers(self, count: int = 20) -> Result[User]:
        """
        Retrieves a list of verified followers for the user.

        Parameters
        ----------
        count : :class:`int`, default=20
            The number of verified followers to retrieve.

        Returns
        -------
        Result[:class:`User`]
            A list of User objects representing the verified followers.

        See Also
        --------
        Client.get_user_verified_followers
        """
        return self._client.get_user_verified_followers(self.id, count)

    def get_followers_you_know(self, count: int = 20) -> Result[User]:
        """
        Retrieves a list of followers whom the user might know.

        Parameters
        ----------
        count : :class:`int`, default=20
            The number of followers you might know to retrieve.

        Returns
        -------
        Result[:class:`User`]
            A list of User objects representing the followers you might know.

        See Also
        --------
        Client.get_user_followers_you_know
        """
        return self._client.get_user_followers_you_know(self.id, count)

    def get_following(self, count: int = 20) -> Result[User]:
        """
        Retrieves a list of users whom the user is following.

        Parameters
        ----------
        count : :class:`int`, default=20
            The number of following users to retrieve.

        Returns
        -------
        Result[:class:`User`]
            A list of User objects representing the users being followed.

        See Also
        --------
        Client.get_user_following
        """
        return self._client.get_user_following(self.id, count)

    def get_subscriptions(self, count: int = 20) -> Result[User]:
        """
        Retrieves a list of users whom the user is subscribed to.

        Parameters
        ----------
        count : :class:`int`, default=20
            The number of subscriptions to retrieve.

        Returns
        -------
        Result[:class:`User`]
            A list of User objects representing the subscribed users.

        See Also
        --------
        Client.get_user_subscriptions
        """
        return self._client.get_user_subscriptions(self.id, count)

    def get_latest_followers(
        self, count: int | None = None, cursor: str | None = None
    ) -> Result[User]:
        """
        Retrieves the latest followers.
        Max count : 200
        """
        return self._client.get_latest_followers(
            self.id, count=count, cursor=cursor
        )

    def get_latest_friends(
        self, count: int | None = None, cursor: str | None = None
    ) -> Result[User]:
        """
        Retrieves the latest friends (following users).
        Max count : 200
        """
        return self._client.get_latest_friends(
            self.id, count=count, cursor=cursor
        )

    def send_dm(
        self, text: str, media_id: str = None, reply_to = None
    ) -> Message:
        """
        Send a direct message to the user.

        Parameters
        ----------
        text : :class:`str`
            The text content of the direct message.
        media_id : :class:`str`, default=None
            The media ID associated with any media content
            to be included in the message.
            Media ID can be received by using the :func:`.upload_media` method.
        reply_to : :class:`str`, default=None
            Message ID to reply to.

        Returns
        -------
        :class:`Message`
            `Message` object containing information about the message sent.

        Examples
        --------
        >>> # send DM with media
        >>> media_id = client.upload_media('image.png')
        >>> message = user.send_dm('text', media_id)
        >>> print(message)
        <Message id="...">

        See Also
        --------
        Client.upload_media
        Client.send_dm
        """
        return self._client.send_dm(self.id, text, media_id, reply_to)

    def get_dm_history(self, max_id: str = None) -> Result[Message]:
        """
        Retrieves the DM conversation history with the user.

        Parameters
        ----------
        max_id : :class:`str`, default=None
            If specified, retrieves messages older than the specified max_id.

        Returns
        -------
        Result[:class:`Message`]
            A Result object containing a list of Message objects representing
            the DM conversation history.

        Examples
        --------
        >>> messages = user.get_dm_history()
        >>> for message in messages:
        >>>     print(message)
        <Message id="...">
        <Message id="...">
        ...
        ...

        >>> more_messages = messages.next()  # Retrieve more messages
        >>> for message in more_messages:
        >>>     print(message)
        <Message id="...">
        <Message id="...">
        ...
        ...
        """
        return self._client.get_dm_history(self.id, max_id)

    def get_highlights_tweets(self, count: int = 20, cursor: str | None = None) -> Result[Tweet]:
        """
        Retrieves highlighted tweets from the user's timeline.

        Parameters
        ----------
        count : :class:`int`, default=20
            The number of tweets to retrieve.

        Returns
        -------
        Result[:class:`Tweet`]
            An instance of the `Result` class containing the highlighted tweets.

        Examples
        --------
        >>> result = user.get_highlights_tweets()
        >>> for tweet in result:
        ...     print(tweet)
        <Tweet id="...">
        <Tweet id="...">
        ...
        ...

        >>> more_results = result.next()  # Retrieve more highlighted tweets
        >>> for tweet in more_results:
        ...     print(tweet)
        <Tweet id="...">
        <Tweet id="...">
        ...
        ...
        """
        return self._client.get_user_highlights_tweets(self.id, count, cursor)

    def update(self) -> None:
        new = self._client.get_user_by_id(self.id)
        self.__dict__.update(new.__dict__)

    def __repr__(self) -> str:
        return f'<User id="{self.id}">'

    def __eq__(self, __value: object) -> bool:
        return isinstance(__value, User) and self.id == __value.id

    def __ne__(self, __value: object) -> bool:
        return not self == __value
