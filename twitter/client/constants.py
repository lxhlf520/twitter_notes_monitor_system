# This token is common to all accounts and does not need to be changed.
TOKEN = 'AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA'

DOMAIN = 'x.com'

JSCODE = """
window = global;
window.self = window;
window.__SCRIPTS_LOADED__ = {};
window.__SCRIPTS_LOADED__.vendor = true;
window.webpackChunk_twitter_responsive_web = [];
%s
function getExportValues() {
    try {
        const exportValues = {};
        if (self.webpackChunk_twitter_responsive_web && 
            self.webpackChunk_twitter_responsive_web[0] && 
            self.webpackChunk_twitter_responsive_web[0][1]) {
                
            const moduleFunctions = self.webpackChunk_twitter_responsive_web[0][1];
            
            Object.values(moduleFunctions).forEach(func => {
                try {
                    if (typeof func === 'function' && func.length === 1) {
                        const temp = {};
                        func(temp);
                        if (temp.exports && 
                            typeof temp.exports === 'object' && 
                            temp.exports.operationName) {
                            exportValues[temp.exports.operationName] = temp.exports;
                        }
                    }
                } catch (err) {
                    console.log('Module processing error:', err.message);
                }
            });
        }
        return exportValues;
    } catch (err) {
        console.log('Main execution error:', err.message);
        return {};
    }
}
"""


APPEND_EXPORT_VALUES = {
    "CommunitiesExploreTimeline": {
        "queryId": "JsTAPsfXO4e4MJSKGjEOLw",
        "operationName": "CommunitiesExploreTimeline",
        "operationType": "query",
        "metadata": {
            "featureSwitches": [
                "rweb_video_screen_enabled",
                "payments_enabled",
                "profile_label_improvements_pcf_label_in_post_enabled",
                "rweb_tipjar_consumption_enabled",
                "verified_phone_label_enabled",
                "creator_subscriptions_tweet_preview_api_enabled",
                "responsive_web_graphql_timeline_navigation_enabled",
                "responsive_web_graphql_skip_user_profile_image_extensions_enabled",
                "premium_content_api_read_enabled",
                "communities_web_enable_tweet_community_results_fetch",
                "c9s_tweet_anatomy_moderator_badge_enabled",
                "responsive_web_grok_analyze_button_fetch_trends_enabled",
                "responsive_web_grok_analyze_post_followups_enabled",
                "responsive_web_jetfuel_frame",
                "responsive_web_grok_share_attachment_enabled",
                "articles_preview_enabled",
                "responsive_web_edit_tweet_api_enabled",
                "graphql_is_translatable_rweb_tweet_is_translatable_enabled",
                "view_counts_everywhere_api_enabled",
                "longform_notetweets_consumption_enabled",
                "responsive_web_twitter_article_tweet_consumption_enabled",
                "tweet_awards_web_tipping_enabled",
                "responsive_web_grok_show_grok_translated_post",
                "responsive_web_grok_analysis_button_from_backend",
                "creator_subscriptions_quote_tweet_preview_enabled",
                "freedom_of_speech_not_reach_fetch_enabled",
                "standardized_nudges_misinfo",
                "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled",
                "longform_notetweets_rich_text_read_enabled",
                "longform_notetweets_inline_media_enabled",
                "responsive_web_grok_image_annotation_enabled",
                "responsive_web_grok_imagine_annotation_enabled",
                "responsive_web_grok_community_note_auto_translation_is_enabled",
                "responsive_web_enhance_cards_enabled"
            ],
            "fieldToggles": [
                "withAuxiliaryUserLabels",
                "withArticleRichContentState",
                "withArticlePlainText",
                "withGrokAnalyze",
                "withDisallowedReplyControls"
            ]
        }
    },
    "CommunityQuery": {
        "queryId": "2W09l7nD7ZbxGQHXvfB22w",
        "metadata": {
            "featureSwitches": ["c9s_list_members_action_api_enabled", "c9s_superc9s_indication_enabled"]
        },
        "name": "CommunityQuery",
        "operationKind": "query"
    },
    "JoinCommunity" :{
        "queryId": "Fg4TfDIaNYGFlu_Wqy2lrg",
        "operationName": "JoinCommunity",
        "operationType": "mutation",
        "metadata": {
            "featureSwitches": [
                "payments_enabled",
                "profile_label_improvements_pcf_label_in_post_enabled",
                "rweb_tipjar_consumption_enabled",
                "verified_phone_label_enabled",
                "responsive_web_graphql_skip_user_profile_image_extensions_enabled",
                "responsive_web_graphql_timeline_navigation_enabled"
            ],
            "fieldToggles": [
                "withAuxiliaryUserLabels"
            ]
        }
    },
    "BirdwatchFetchGlobalTimeline": {
        "queryId": "m1B2Vwf-_Xuq4aou_9ncrA",
        "operationName": "BirdwatchFetchGlobalTimeline",
        "operationType": "query",
        "metadata": {
            "featureSwitches": [
                "rweb_video_screen_enabled",
                "profile_label_improvements_pcf_label_in_post_enabled",
                "responsive_web_profile_redirect_enabled",
                "rweb_tipjar_consumption_enabled",
                "verified_phone_label_enabled",
                "responsive_web_graphql_timeline_navigation_enabled",
                "rweb_cashtags_enabled",
                "responsive_web_graphql_skip_user_profile_image_extensions_enabled",
                "creator_subscriptions_tweet_preview_api_enabled",
                "premium_content_api_read_enabled",
                "communities_web_enable_tweet_community_results_fetch",
                "c9s_tweet_anatomy_moderator_badge_enabled",
                "responsive_web_grok_analyze_button_fetch_trends_enabled",
                "responsive_web_grok_analyze_post_followups_enabled",
                "rweb_cashtags_composer_attachment_enabled",
                "responsive_web_jetfuel_frame",
                "responsive_web_grok_share_attachment_enabled",
                "responsive_web_grok_annotations_enabled",
                "articles_preview_enabled",
                "responsive_web_edit_tweet_api_enabled",
                "graphql_is_translatable_rweb_tweet_is_translatable_enabled",
                "view_counts_everywhere_api_enabled",
                "longform_notetweets_consumption_enabled",
                "responsive_web_twitter_article_tweet_consumption_enabled",
                "content_disclosure_indicator_enabled",
                "content_disclosure_ai_generated_indicator_enabled",
                "responsive_web_grok_show_grok_translated_post",
                "responsive_web_grok_analysis_button_from_backend",
                "post_ctas_fetch_enabled",
                "freedom_of_speech_not_reach_fetch_enabled",
                "standardized_nudges_misinfo",
                "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled",
                "longform_notetweets_rich_text_read_enabled",
                "longform_notetweets_inline_media_enabled",
                "responsive_web_grok_image_annotation_enabled",
                "responsive_web_grok_imagine_annotation_enabled",
                "responsive_web_grok_community_note_auto_translation_is_enabled",
                "responsive_web_enhance_cards_enabled"
            ],
            "fieldToggles": []
        }
    },
    "GenericTimelineById": {
        "queryId": "VrAHfTlEBd6qq1IJlOvBqQ",
        "operationName": "GenericTimelineById",
        "operationType": "query",
        "metadata": {
            "featureSwitches": [
                "rweb_video_screen_enabled",
                "rweb_cashtags_enabled",
                "profile_label_improvements_pcf_label_in_post_enabled",
                "responsive_web_profile_redirect_enabled",
                "rweb_tipjar_consumption_enabled",
                "verified_phone_label_enabled",
                "creator_subscriptions_tweet_preview_api_enabled",
                "responsive_web_graphql_timeline_navigation_enabled",
                "responsive_web_graphql_skip_user_profile_image_extensions_enabled",
                "premium_content_api_read_enabled",
                "communities_web_enable_tweet_community_results_fetch",
                "c9s_tweet_anatomy_moderator_badge_enabled",
                "responsive_web_grok_analyze_button_fetch_trends_enabled",
                "responsive_web_grok_analyze_post_followups_enabled",
                "rweb_cashtags_composer_attachment_enabled",
                "responsive_web_jetfuel_frame",
                "responsive_web_grok_share_attachment_enabled",
                "responsive_web_grok_annotations_enabled",
                "articles_preview_enabled",
                "responsive_web_edit_tweet_api_enabled",
                "graphql_is_translatable_rweb_tweet_is_translatable_enabled",
                "view_counts_everywhere_api_enabled",
                "longform_notetweets_consumption_enabled",
                "responsive_web_twitter_article_tweet_consumption_enabled",
                "content_disclosure_indicator_enabled",
                "content_disclosure_ai_generated_indicator_enabled",
                "responsive_web_grok_show_grok_translated_post",
                "responsive_web_grok_analysis_button_from_backend",
                "post_ctas_fetch_enabled",
                "freedom_of_speech_not_reach_fetch_enabled",
                "standardized_nudges_misinfo",
                "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled",
                "longform_notetweets_rich_text_read_enabled",
                "longform_notetweets_inline_media_enabled",
                "responsive_web_grok_image_annotation_enabled",
                "responsive_web_grok_imagine_annotation_enabled",
                "responsive_web_grok_community_note_auto_translation_is_enabled",
                "responsive_web_enhance_cards_enabled"
            ],
            "fieldToggles": []
        }
    }
}