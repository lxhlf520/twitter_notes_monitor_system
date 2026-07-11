from typing import Dict, Any, Optional, List, Tuple, Generator
import json
from .tweet import Tweet
from .user import User


def parse_user_data(data: User) -> Generator[Tuple, None, None]:
    """
    将用户数据解析为BaseUser字典
    """
    # 构建扩展信息
    extend = {
        'is_blue_verified': data.is_blue_verified,
        'profile_banner_url': data.profile_banner_url,
        'profile_image_shape': data.profile_image_shape,
        'possibly_sensitive': data.possibly_sensitive,
        'default_profile': data.default_profile,
        'default_profile_image': data.default_profile_image,
        'has_custom_timelines': data.has_custom_timelines,
        'is_translator': data.is_translator,
        'translator_type': data.translator_type,
        'want_retweets': data.want_retweets,
        'has_graduated_access': data.has_graduated_access,
        'premium_gifting_eligible': data.premium_gifting_eligible,
        'creator_subscriptions_count': data.creator_subscriptions_count,
        'affiliates_highlighted_label': data.affiliates_highlighted_label,
        'highlights_info': data.highlights_info,
        'tipjar_settings': data.tipjar_settings,
        'business_account': data.business_account,
        'legacy_extended_profile': data.legacy_extended_profile,
        'verification_info': data.verification_info,
        'relationship_perspectives': data.relationship_perspectives
    }
    user_item = {
        'user_id': data.id,
        'url': f'https://x.com/{data.screen_name}' if data.screen_name else '',
        'avatar': data.avatar_url,
        'name': data.name,
        'username': data.screen_name,
        'gender': 0,  # twikit中没有性别字段，默认为0
        'website': data.url,
        'description': data.description,
        'location': data.location,
        'follower_count': data.followers_count,
        'following_count': data.following_count,
        'content_count': data.statuses_count,
        'verified': data.verified,  # 返回 "gold", "blue", "none"
        'extend': json.dumps(extend, ensure_ascii=False),  # 扩展字段，存储原始数据
        'platform': 'twitter',
        'created_at': data.created_at
    }
    return user_item

def parse_post_data(data: List[Tweet]) -> Generator[Tuple, None, None]:
    """
    将贴子数据解析为BasePost和BaseMedia字典
    """
    posts = []
    for tweet in data:
        # 解析帖子数据
        post = {
            'post_id': tweet.id,
            'user_id': tweet.user.id,
            'author': tweet.user.name,
            'content': tweet.full_text,
            'url': tweet.url,
            'pub_time': tweet.created_at,
            'share_count': tweet.retweet_count,  # Twitter的分享就是转发
            'repost_count': tweet.retweet_count,
            'comment_count': tweet.reply_count,
            'like_count': tweet.favorite_count,
            'view_count': tweet.view_count or 0,
            'favorites': tweet.favorite_count,
            'extend': json.dumps(tweet._data, ensure_ascii=False),
            'platform': 'twitter'
        }
        posts.append(post)
        
    return posts




def parse_note_data(data: dict) -> dict:
    """
    解析 Community Notes 数据。
    支持两种输入格式：
    1. BirdwatchFetchNotes API 返回格式（含 misleading_birdwatch_notes / not_misleading_birdwatch_notes）
    2. TweetDetail / GenericTimeline 中的 birdwatch_pivot 格式

    返回结构:
    {
        "posts": [...],          # Post 静态信息
        "notes": [...],          # Note 总结信息
        "contributors": [...],   # Contributor 静态信息
    }
    """
    tweet_result = data.get("data", {}).get("tweet_result_by_rest_id", {}).get("result", {})
    
    # 格式1: BirdwatchFetchNotes 响应
    misleading_notes = tweet_result.get("misleading_birdwatch_notes", {}).get("notes", [])
    not_misleading_notes = tweet_result.get("not_misleading_birdwatch_notes", {}).get("notes", [])
    all_notes = misleading_notes + not_misleading_notes

    # 格式2: birdwatch_pivot（来自 TweetDetail/GenericTimeline）
    notes = []
    contributors = []
    
    if all_notes:
        # 处理 BirdwatchFetchNotes 完整格式
        for note in all_notes:
            note_id = note.get("rest_id")
            # --- Note 信息 ---
            note_item = {
                "note_id": note_id,
                "noteId": note_id,  # MongoDB 唯一索引兼容
                "note_status": note.get("rating_status"),
                "note_content": note.get("data_v1", {}).get("summary", {}).get("text", ""),
                "note_source_links": _extract_source_links(note),
                "note_create_time": note.get("created_at"),
                "note_type": _classify_note_type(note),
                "AI_note": _detect_ai_note(note),
                "note_status_detail": _rating_status_detail(note),
                "note_status_algorithm": note.get("decided_by", ""),
                "note_author": note.get("birdwatch_profile", {}).get("alias", ""),
                "note_author_writing_impact": "",
                "note_author_rating_impact": "",
                "note_author_profile_link": _build_profile_link(note),
                "fully_visible_model": note.get("fully_visible_model", False),
                "classification": note.get("data_v1", {}).get("classification", ""),
                "misleading_tags": note.get("data_v1", {}).get("misleading_tags", []),
                "helpful_tags": note.get("helpful_tags", []),
                "not_helpful_tags": note.get("not_helpful_tags", []),
                "language": note.get("language", ""),
                "is_api_author": note.get("is_api_author", False),
                "is_media_note": note.get("is_media_note", False),
                "can_appeal": note.get("can_appeal", False),
                "appeal_status": note.get("appeal_status", ""),
                "source_data": json.dumps(note, ensure_ascii=False),
            }
            notes.append(note_item)

            # --- Contributor 信息 ---
            profile = note.get("birdwatch_profile", {})
            alias = profile.get("alias", "")
            notes_count = profile.get("notes_count", {})
            ratings_count = profile.get("ratings_count", {})
            successful = ratings_count.get("successful", {})
            unsuccessful = ratings_count.get("unsuccessful", {})

            contributor_item = {
                "note_id": note_id,
                "participantId": alias,  # MongoDB 唯一索引兼容
                "author_name": alias,
                "author_profile_link": f"https://x.com/i/communitynotes/u/{alias}" if alias else "",
                "author_id": alias,
                "author_AI": "Experimental AI Note Writer" if note.get("is_api_author") else "Human",
                "top_writer": False,
                "notes_awaiting_more_ratings": notes_count.get("awaiting_more_ratings", 0),
                "notes_currently_rated_helpful": notes_count.get("currently_rated_helpful", 0),
                "notes_currently_rated_not_helpful": notes_count.get("currently_rated_not_helpful", 0),
                "ratings_successful_total": successful.get("total", 0),
                "ratings_successful_helpful": successful.get("helpful_count", 0),
                "ratings_unsuccessful_total": unsuccessful.get("total", 0),
                "source_data": json.dumps(profile, ensure_ascii=False),
            }
            contributors.append(contributor_item)
    else:
        # 尝试从 birdwatch_pivot 格式提取
        birdwatch_pivot = tweet_result.get("birdwatch_pivot", {})
        if birdwatch_pivot:
            pivot_note = birdwatch_pivot.get("note", {})
            note_id = pivot_note.get("rest_id")
            if note_id:
                note_content = birdwatch_pivot.get("subtitle", {}).get("text", "")
                note_item = {
                    "note_id": note_id,
                    "noteId": note_id,  # MongoDB 唯一索引兼容
                    "note_status": "CurrentlyRatedHelpful",  # birdwatch_pivot 出现在 rated_helpful 推文中
                    "note_content": note_content,
                    "note_source_links": _extract_pivot_source_links(birdwatch_pivot),
                    "note_create_time": "",
                    "note_type": "",
                    "AI_note": _detect_pivot_ai_note(pivot_note),
                    "note_status_detail": "This note has been rated helpful by the community",
                    "note_status_algorithm": "",
                    "note_author": "",
                    "note_author_writing_impact": "",
                    "note_author_rating_impact": "",
                    "note_author_profile_link": "",
                    "fully_visible_model": False,
                    "classification": birdwatch_pivot.get("visualStyle", ""),
                    "misleading_tags": [],
                    "helpful_tags": [],
                    "not_helpful_tags": [],
                    "language": pivot_note.get("language", ""),
                    "is_api_author": pivot_note.get("grok_translated_community_note_with_availability", {}).get("is_available", False),
                    "is_media_note": False,
                    "can_appeal": False,
                    "appeal_status": "",
                    "source_data": json.dumps(birdwatch_pivot, ensure_ascii=False),
                }
                notes.append(note_item)
                # birdwatch_pivot 没有 contributor 数据，创建空记录
                contributor_item = {
                    "note_id": note_id,
                    "participantId": note_id,  # MongoDB 唯一索引兼容
                    "author_name": "",
                    "author_profile_link": "",
                    "author_id": "",
                    "author_AI": "Unknown",
                    "top_writer": False,
                    "notes_awaiting_more_ratings": 0,
                    "notes_currently_rated_helpful": 0,
                    "notes_currently_rated_not_helpful": 0,
                    "ratings_successful_total": 0,
                    "ratings_successful_helpful": 0,
                    "ratings_unsuccessful_total": 0,
                    "source_data": "{}",
                }
                contributors.append(contributor_item)

    return {"notes": notes, "contributors": contributors}


def _extract_source_links(note: dict) -> list[str]:
    """从 note 的 summary entities 中提取外部链接"""
    entities = note.get("data_v1", {}).get("summary", {}).get("entities", [])
    links = []
    for entity in entities:
        ref = entity.get("ref", {})
        if ref.get("type") == "TimelineUrl":
            links.append(ref.get("url", ""))
    return links


def _classify_note_type(note: dict) -> str:
    """根据 classification 和 tags 判断 Note 类型"""
    classification = note.get("data_v1", {}).get("classification", "")
    if classification == "MisinformedOrPotentiallyMisleading":
        return "Notes suggesting context to be shown with the post"
    elif classification == "NotMisleading":
        return "Notes indicating the post is not misleading"
    return classification


def _detect_ai_note(note: dict) -> str:
    """检测 Note 是否由 AI 生成"""
    if note.get("is_api_author"):
        grok_avail = note.get("grok_translated_community_note_with_availability", {})
        if grok_avail.get("is_available"):
            grok_data = grok_avail.get("data", {})
            return f"AI (Grok) translated: {grok_data.get('source_language', '')} -> {grok_data.get('destination_language', '')}"
        return "Proposed by an experimental AI Note Writer"
    return ""


def _rating_status_detail(note: dict) -> str:
    """根据 rating_status 生成可读的状态描述"""
    status = note.get("rating_status", "")
    if status == "CurrentlyRatedHelpful":
        return "This note has been rated helpful by the community"
    elif status == "CurrentlyRatedNotHelpful":
        return "This note has been rated not helpful by the community"
    elif status == "NeedsMoreRatings":
        return "This note hasn't yet been rated. You can help by rating it."
    return status


def _build_profile_link(note: dict) -> str:
    """构建 Contributor 主页链接"""
    alias = note.get("birdwatch_profile", {}).get("alias", "")
    if alias:
        return f"https://x.com/i/communitynotes/u/{alias}"
    return ""


def _extract_pivot_source_links(pivot: dict) -> list[str]:
    """从 birdwatch_pivot 的 subtitle entities 中提取外部链接"""
    entities = pivot.get("subtitle", {}).get("entities", [])
    links = []
    for entity in entities:
        ref = entity.get("ref", {})
        if ref.get("type") == "TimelineUrl":
            links.append(ref.get("url", ref.get("expandedUrl", "")))
    return links


def _detect_pivot_ai_note(pivot_note: dict) -> str:
    """从 birdwatch_pivot.note 检测是否为 AI 笔记"""
    grok = pivot_note.get("grok_translated_community_note_with_availability", {})
    if grok.get("is_available"):
        return "AI (Grok) translated"
    return ""