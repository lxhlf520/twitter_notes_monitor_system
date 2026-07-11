# 数据库集合字段说明

## 1. twitter_accounts — Twitter 账号池

| 字段 | 类型 | 说明 |
|------|------|------|
| username | string | 账号用户名（唯一索引） |
| cookie | string | Cookie 字符串（`auth_token=xxx; ct0=yyy; ...`） |
| enabled | bool | 是否启用 |
| last_used_at | datetime | 最后使用时间 |
| request_count | int | 累计请求次数 |
| success_count | int | 累计成功次数 |
| fail_count | int | 累计失败次数 |
| last_error | string | 最后一次错误信息 |
| cooldown_until | datetime | 冷却截止时间（冷却中不可用） |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 更新时间 |

**索引**: `username(unique)`, `enabled`, `cooldown_until`

---

## 2. x_com_post_new — 待评级笔记推文

| 字段 | 类型 | 说明 |
|------|------|------|
| post_id | string | 推文 ID（唯一索引） |
| user_id | string | 作者用户 ID |
| author | string | 作者显示名称 |
| content | string | 推文全文 |
| url | string | 推文链接 |
| pub_time | string | 发布时间 |
| share_count | int | 转发数 |
| repost_count | int | 转发数（同 share_count） |
| comment_count | int | 回复数 |
| like_count | int | 点赞数 |
| view_count | int | 阅读数 |
| favorites | int | 收藏数 |
| extend | string | 原始 API 响应 JSON |
| platform | string | 平台标识（固定 `twitter`） |
| captured_at | long | 抓取时间戳（毫秒） |
| noteId | string | 关联笔记 ID（有笔记时） |

**索引**: `post_id(unique)`, `noteId`, `capturedAt`

---

## 3. x_com_post_new_metrics — 待评级推文指标历史

| 字段 | 类型 | 说明 |
|------|------|------|
| post_id | string | 推文 ID |
| like_count | int | 点赞数 |
| reply_count | int | 回复数 |
| retweet_count | int | 转发数 |
| view_count | int | 阅读数 |
| bookmark_count | int | 收藏数 |
| captured_at | long | 采集时间戳（毫秒） |

**索引**: `(post_id, captured_at)`

---

## 4. x_com_post_helpful — 已评级 Helpful 推文

| 字段 | 类型 | 说明 |
|------|------|------|
| post_id | string | 推文 ID（唯一索引） |
| user_id | string | 作者用户 ID |
| author | string | 作者显示名称 |
| content | string | 推文全文 |
| url | string | 推文链接 |
| pub_time | string | 发布时间 |
| share_count | int | 转发数 |
| repost_count | int | 转发数 |
| comment_count | int | 回复数 |
| like_count | int | 点赞数 |
| view_count | int | 阅读数 |
| favorites | int | 收藏数 |
| extend | string | 原始 API 响应 JSON |
| platform | string | 平台标识（固定 `twitter`） |
| captured_at | long | 抓取时间戳（毫秒） |
| noteId | string | 关联笔记 ID |
| source_data | string | TweetDetail 原始响应 JSON（笔记提取用） |

**索引**: `post_id(unique)`, `noteId`, `capturedAt`

---

## 5. x_com_post_helpful_metrics — 已评级推文指标历史

| 字段 | 类型 | 说明 |
|------|------|------|
| post_id | string | 推文 ID |
| like_count | int | 点赞数 |
| reply_count | int | 回复数 |
| retweet_count | int | 转发数 |
| view_count | int | 阅读数 |
| bookmark_count | int | 收藏数 |
| captured_at | long | 采集时间戳（毫秒） |

**索引**: `(post_id, captured_at)`

---

## 6. x_com_notes — 社区笔记

| 字段 | 类型 | 说明 |
|------|------|------|
| note_id | string | 笔记唯一 ID（唯一索引） |
| noteId | string | 笔记唯一 ID（兼容旧索引，同 note_id） |
| note_status | string | 评级状态（`CurrentlyRatedHelpful` / `NeedsMoreRatings` 等） |
| note_content | string | 笔记正文摘要 |
| note_source_links | array[string] | 引用来源链接列表 |
| note_create_time | string | 笔记创建时间 |
| note_type | string | 笔记分类描述 |
| AI_note | string | AI 笔记标记（如 `AI (Grok) translated`） |
| note_status_detail | string | 状态可读描述 |
| note_status_algorithm | string | 评级算法标识 |
| note_author | string | 笔记作者别名 |
| note_author_writing_impact | string | 作者写作影响力分 |
| note_author_rating_impact | string | 作者评级影响力分 |
| note_author_profile_link | string | 作者社区资料页链接 |
| fully_visible_model | bool | 是否完全可见 |
| classification | string | 误导分类（`MisinformedOrPotentiallyMisleading` / `NotMisleading` 等） |
| misleading_tags | array[string] | 误导标签列表 |
| helpful_tags | array[string] | 有帮助标签列表 |
| not_helpful_tags | array[string] | 无帮助标签列表 |
| language | string | 笔记语言代码 |
| is_api_author | bool | 是否 API 作者（AI 笔记标记） |
| is_media_note | bool | 是否媒体笔记 |
| can_appeal | bool | 是否可申诉 |
| appeal_status | string | 申诉状态 |
| source_data | string | birdwatch_pivot 或 note 的原始 JSON |

**索引**: `note_id(unique)`, `post_id`, `noteId(unique)`

---

## 7. x_com_contributors — 笔记贡献者

| 字段 | 类型 | 说明 |
|------|------|------|
| note_id | string | 关联笔记 ID（唯一索引，一一对应） |
| participantId | string | 贡献者标识（兼容旧索引，同 author_id） |
| author_name | string | 贡献者名称 |
| author_profile_link | string | 社区资料页链接 |
| author_id | string | 贡献者 ID |
| author_AI | string | 是否 AI 作者（`Human` / `Experimental AI Note Writer`） |
| top_writer | bool | 是否顶级作者 |
| notes_awaiting_more_ratings | int | 待评级笔记数 |
| notes_currently_rated_helpful | int | 已评为 helpful 的笔记数 |
| notes_currently_rated_not_helpful | int | 已评为 not helpful 的笔记数 |
| ratings_successful_total | int | 成功评级总数 |
| ratings_successful_helpful | int | 评为 helpful 的评级数 |
| ratings_unsuccessful_total | int | 未成功评级总数 |
| source_data | string | 原始 birdwatch_profile JSON |

**索引**: `note_id(unique)`, `author_id`, `participantId(unique)`

---

## 8. x_com_api_raw — API 原始响应

| 字段 | 类型 | 说明 |
|------|------|------|
| endpoint | string | 接口名（`TweetDetail` / `GenericTimeline` / `BirdwatchFetchGlobalTimeline`） |
| post_id | string | 关联推文 ID |
| response | object | 完整 API 响应体 |
| captured_at | datetime | 抓取时间 |

**索引**: `(endpoint, captured_at)`, `post_id`

---

## 9. x_com_health_snapshots — 健康快照

| 字段 | 类型 | 说明 |
|------|------|------|
| reported_at | string | 报告时间（ISO 格式） |
| uptime_seconds | float | 系统运行秒数 |
| account_snapshot | object | 账号状态快照 |
| ├ mode | string | 运行模式（`direct` / `rpc`） |
| ├ total | int | 账号总数 |
| ├ available | int | 可用账号数 |
| ├ cooldown | int | 冷却中账号数 |
| ├ disabled | int | 已禁用账号数 |
| └ accounts | array | 逐账号详情 |
| &nbsp;&nbsp; ├ username | string | 账号名 |
| &nbsp;&nbsp; ├ status | string | 状态（`available` / `cooldown` / `disabled`） |
| &nbsp;&nbsp; ├ success_count | int | 成功请求数 |
| &nbsp;&nbsp; ├ fail_count | int | 失败请求数 |
| &nbsp;&nbsp; ├ consecutive_failures | int | 连续失败次数 |
| &nbsp;&nbsp; ├ last_used_at | string | 最后使用时间 |
| &nbsp;&nbsp; ├ cooldown_until | string | 冷却到期时间 |
| &nbsp;&nbsp; └ last_error | string | 最后错误信息 |
| task_health | object | 任务健康度 |
| ├ crawl | object | 笔记抓取任务 |
| │ ├ task_name | string | 任务名 |
| │ ├ expected_interval_seconds | int | 预期间隔秒数 |
| │ ├ last_started_at | string | 最后启动时间 |
| │ ├ last_succeeded_at | string | 最后成功时间 |
| │ ├ last_failed_at | string | 最后失败时间 |
| │ ├ last_error | string | 最后错误信息 |
| │ ├ last_duration_seconds | float | 最后执行耗时 |
| │ ├ total_runs | int | 总执行次数 |
| │ ├ success_runs | int | 成功次数 |
| │ ├ fail_runs | int | 失败次数 |
| │ ├ consecutive_failures | int | 连续失败次数 |
| │ ├ success_rate | float | 成功率（0.0~1.0） |
| │ ├ is_overdue | bool | 是否超时未执行 |
| │ └ overdue_seconds | float | 超时秒数 |
| ├ update_new | object | New 源指标更新任务（同上结构） |
| └ update_helpful | object | Helpful 源指标更新任务（同上结构） |

**索引**: `reported_at`, `healthy`

---

## 10. x_com_signature_cache — 签名材料缓存

两种数据类型共用同一集合：

### 10a. 账号签名材料（按 username）

| 字段 | 类型 | 说明 |
|------|------|------|
| username | string | 账号用户名（唯一索引） |
| key_bytes | array[int] | 签名 key 字节数组 |
| key_byte_indices | array[int] | key 字节索引 |
| arr_2d | array[array[int]] | 二维数组材料 |
| updated_at | datetime | 更新时间 |

### 10b. GraphQL 端点参数（全局共享）

| 字段 | 类型 | 说明 |
|------|------|------|
| _type | string | 固定 `endpoint_params` |
| params | object | 端点参数字典（key=端点名, value={endpoint, params}） |
| updated_at | datetime | 更新时间 |

**索引**: `username(unique, sparse)`, `_type`

---

## 11. x_com_post_update_status — 推文更新状态

| 字段 | 类型 | 说明 |
|------|------|------|
| post_id | string | 推文 ID |
| source | string | 数据源（`new` / `helpful`） |
| status | string | 状态（`success` / `failed` / `deleted`） |
| error | string | 失败时的错误信息 |
| metrics | object | 成功时的指标快照 |
| captured_at | datetime | 记录时间 |

**索引**: `(post_id, captured_at)`, `status`
