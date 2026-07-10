from __future__ import annotations

from typing import TYPE_CHECKING

import m3u8
import webvtt
from m3u8 import M3U8

if TYPE_CHECKING:
    from .client.client import Client


class Media:
    """
    表示媒体对象的基类。

    属性
    ----------
    id : :class:`str`
        媒体ID。
    display_url : :class:`str`
        显示URL。
    expanded_url : :class:`str`
        扩展的显示URL。
    media_url : :class:`str`
        媒体URL。
    source_status_id : :class:`str`
        源推文ID。
    source_user_id : :class:`str`
        发布源推文的用户ID。
    type : :class:`str`
        媒体类型。
    url : :class:`str`
        媒体的URL。
    sizes : :class:`dict`
        媒体的尺寸。
    original_info : :class:`str`
    width : :class:`int`
        媒体的宽度。
    height : :class:`int`
        媒体的高度。
    focus_rects : :class:`list`
    """
    def __init__(self, client: Client, data: dict) -> None:
        self._client = client
        self._data = data

    @property
    def id(self) -> str:
        return self._data.get('id_str')

    @property
    def display_url(self) -> str:
        return self._data.get('display_url')

    @property
    def expanded_url(self) -> str:
        return self._data.get('expanded_url')

    @property
    def media_url(self) -> str:
        return self._data.get('media_url_https')

    @property
    def source_status_id(self) -> str:
        return self._data.get('source_status_id_str')

    @property
    def source_user_id(self) -> str:
        return self._data.get('source_user_id_str')

    @property
    def type(self) -> str:
        return self._data.get('type')

    @property
    def url(self) -> str:
        return self._data.get('url')

    # 添加源用户
    @property
    def sizes(self) -> dict:
        return self._data.get('sizes')

    @property
    def original_info(self) -> str:
        return self._data.get('original_info')

    @property
    def width(self) -> int:
        return self.original_info.get('width')

    @property
    def height(self) -> int:
        return self.original_info.get('height')

    @property
    def focus_rects(self) -> list:
        return self.original_info.get('focus_rects')
    
    @property
    def info(self) -> dict:
        pass

    def get(self) -> bytes:
        response = self._client.http.get(self.media_url)
        return response.content

    def download(self, output_path: str) -> None:
        with open(output_path, 'wb') as f:
            f.write(self.get())

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__} id={self.id}>'


class Photo(Media):
    """
    表示照片媒体对象的类。

    属性
    ----------
    features : :class:`dict`
        照片的特征。
    """
    @property
    def features(self) -> dict:
        return self._data.get('features')


class Stream:
    """
    Stream类表示媒体流

    属性
    ----------
    url : :class:`str`
        流的URL。
    bitrate : :class:`int`
        流的比特率。
    content_type : :class:`str`
        流内容的MIME类型。
    """
    def __init__(self, client: Client, data: dict) -> None:
        self._client = client
        self._data = data

    @property
    def url(self) -> str:
        return self._data.get('url')

    @property
    def bitrate(self) -> int:
        return self._data.get('bitrate')

    @property
    def content_type(self) -> str:
        return self._data.get('content-type')

    def get(self) -> bytes:
        """
        获取流内容。

        返回
        -------
        :class:`bytes`
            流的原始内容。
        """
        response = self._client.http.get(self.url)
        return response.content

    def download(self, output_path: str) -> None:
        """
        下载流内容并保存到指定文件。

        参数
        ----------
        output_path : :class:`str`
            下载文件将被保存的路径。
        """
        with open(output_path, 'wb') as f:
            f.write(self.get())

    def __repr__(self) -> str:
        return f'<Stream url="{self.url}">'


class AnimatedGif(Media):
    """
    表示动画GIF媒体对象的类。

    属性
    ----------
    video_info : :class:`dict`
        GIF的视频信息。
    aspect_ratio : :class:`tuple[int, int]`
        GIF的宽高比。
    streams : list[:class:`Stream`]
        GIF的视频流列表。
    """
    @property
    def video_info(self) -> dict:
        return self._data.get('video_info')

    @property
    def aspect_ratio(self) -> tuple[int, int]:
        return tuple(self.video_info['aspect_ratio'])

    @property
    def streams(self) -> list:
        return [Stream(self._client, stream_data) for stream_data in self.video_info.get('variants')]


class Video(Media):
    """
    表示视频媒体对象的类。


    .. code-block:: python

        # 视频下载示例
        tweet = client.get_tweet_by_id('00000000000')
        video = tweet.media[0]
        streams = video.streams
        streams[0].download('output.mp4')

    属性
    ----------
    video_info : :class:`dict`
        视频信息。
    aspect_ratio : :class:`tuple[int, int]`
        视频的宽高比。
    duration_millis : :class:`int`
        视频的持续时间（毫秒）。
    streams : list[:class:`Stream`]
        视频的视频流列表。
    """
    def __init__(self, client: Client, data: dict) -> None:
        super().__init__(client, data)
        self._playlist: M3U8 | None = None
        self._subtitles_playlist: M3U8 | None = None
        self._base_url = 'https://video.twimg.com'

    @property
    def video_info(self) -> dict:
        return self._data.get('video_info')

    @property
    def aspect_ratio(self) -> tuple[int, int]:
        return tuple(self.video_info['aspect_ratio'])

    @property
    def duration_millis(self) -> int:
        return self.video_info.get('duration_millis')

    @property
    def _streams(self) -> list:
        return self.video_info.get('variants')

    @property
    def streams(self) -> list[Stream]:
        video_streams = filter(
            lambda x: x['content_type'].startswith('video'),
            self._streams
        )
        return [Stream(self._client, stream_data) for stream_data in video_streams]

    def _get_playlist(self) -> M3U8 | None:
        # 返回包含流信息的M3U8对象。
        if self._playlist:
            return self._playlist
        m3u8_stream = next(
            filter(
                lambda x: x['content_type'] == 'application/x-mpegURL',
                self._streams
            ),
            None
        )
        if not m3u8_stream:
            raise None
        response, _ = self._client.get(m3u8_stream['url'])
        playlist = m3u8.loads(response)
        self._playlist = playlist
        return playlist

    def _get_subtitles_playlist(self) -> M3U8 | None:
        # 返回包含字幕信息的M3U8对象。
        if self._subtitles_playlist:
            return self._subtitles_playlist
        playlist = self._get_playlist()
        if not playlist:
            return None
        subtitles_media = next(
            filter(
                lambda x: x.type == 'SUBTITLES',
                playlist.media
            ),
            None
        )
        if not subtitles_media:
            return None
        response, _ = self._client.get(self._base_url + subtitles_media.uri)
        playlist = m3u8.loads(response)
        self._subtitles_playlist = playlist
        return playlist

    def get_subtitles(self) -> webvtt.WebVTT | None:
        """
        获取视频的字幕。

        返回
        -------
        :class:`webvtt.WebVTT` | None
            返回视频的字幕。如果视频没有字幕，则返回None。
            请参考 https://github.com/glut23/webvtt-py 获取更多信息。

        示例
        --------
        .. code-block:: python

            tweet = client.get_tweet_by_id('00000000000')
            video = tweet.media[0]
            subtitles = video.get_subtitles()
            for l in subtitles:
                print(l.start)
                print(l.end)
                print(l.text)
        """
        subtitles_playlist = self._get_subtitles_playlist()
        if not subtitles_playlist:
            return None
        response, _ = self._client.get(self._base_url + subtitles_playlist.segments[0].uri)
        return webvtt.from_string(response)


MEDIA_TYPE = Video | Photo | AnimatedGif
MEDIA_TYPE_MAPPING = {
    'video': Video,
    'photo': Photo,
    'animated_gif': AnimatedGif
}


def _media_from_data(client, data) -> Media:
    type = data['type']
    cls = MEDIA_TYPE_MAPPING.get(type)
    if not cls:
        print('未知的媒体类型')
        return
    return cls(client, data)
