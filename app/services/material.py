import os
import random
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, List, Optional
from urllib.parse import quote_plus, urlencode, urlparse, urlunsplit, parse_qs

import requests
from loguru import logger
from moviepy.video.io.VideoFileClip import VideoFileClip

from app.config import config
from app.models import const
from app.models.schema import MaterialInfo, VideoAspect, VideoConcatMode
from app.services import material_cache, task_artifacts
from app.services import state as sm
from app.utils import utils

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

# Thread-safe counter for API key rotation
_api_key_counter = 0
_api_key_lock = threading.Lock()


def _safe_public_url(value: Any) -> str | None:
    """
    只保留可公开展示的 HTTP(S) 页面地址，并移除查询参数和凭据。

    素材下载地址可能携带 API Key、签名 JWT 或临时 token。任务清单只需要
    帮助用户回到供应商的公开素材页，不应保存鉴权参数；用户信息形式的 URL
    同样拒绝，避免 ``https://user:pass@example.com`` 一类内容落盘。
    """
    if not isinstance(value, str) or not value.strip():
        return None

    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _creator_info(value: Any) -> dict[str, str] | None:
    """从不同供应商的作者结构中提取统一的公开字段。"""
    if isinstance(value, str) and value.strip():
        return {"name": value.strip()}
    if not isinstance(value, dict):
        return None

    creator: dict[str, str] = {}
    creator_id = value.get("id")
    creator_name = value.get("name") or value.get("username")
    creator_page = _safe_public_url(
        value.get("url") or value.get("profile_url") or value.get("profile_page")
    )
    if creator_id is not None:
        creator["id"] = str(creator_id)
    if creator_name:
        creator["name"] = str(creator_name)
    if creator_page:
        creator["profile_page"] = creator_page
    return creator or None


def _material_source_record(item: MaterialInfo, local_path: str) -> dict[str, Any]:
    """
    为成功下载的素材生成轻量来源记录。

    ``source_info`` 可能来自缓存，甚至来自外部构造的 ``MaterialInfo``，因此
    不能原样写入。这里按白名单重新构造，只保留公开页面、业务标识和尺寸，
    并只记录本地文件名，避免用户目录或 Docker 挂载路径进入任务文件。
    """
    source = item.source_info if isinstance(item.source_info, dict) else {}
    record: dict[str, Any] = {
        "provider": str(item.provider or source.get("provider") or ""),
        "local_file": Path(local_path).name,
        "duration": int(item.duration),
    }

    search_term = source.get("search_term")
    asset_id = source.get("asset_id")
    source_page = _safe_public_url(source.get("source_page"))
    if isinstance(search_term, str) and search_term.strip():
        record["search_term"] = search_term.strip()
    if asset_id not in (None, ""):
        record["asset_id"] = str(asset_id)
    if source_page:
        record["source_page"] = source_page

    creator = _creator_info(source.get("creator"))
    if creator:
        record["creator"] = creator

    raw_rendition = source.get("rendition")
    if isinstance(raw_rendition, dict):
        rendition = {}
        for field in ("id", "width", "height"):
            value = raw_rendition.get(field)
            if value not in (None, ""):
                rendition[field] = str(value) if field == "id" else value
        if rendition:
            record["rendition"] = rendition

    # YouTube-specific provenance fields (whitelist — only if present)
    for field in ("title", "channel", "license_status", "video_id"):
        val = source.get(field)
        if val not in (None, ""):
            record[field] = str(val)
    return record


def _persist_material_sources(
    task_id: str,
    material_sources: list[dict[str, Any]],
) -> None:
    """
    将当前实际下载成功的素材来源补充到任务清单。

    任务记录是辅助能力，不能改变视频下载函数的返回值，也不能因为写盘失败
    中断成片主流程。``patch_script_data`` 会负责原子替换和异常日志；这里仅在
    成功后记录数量，便于确认任务追溯信息是否已经落盘。
    """
    try:
        saved = task_artifacts.patch_script_data(
            task_id,
            material_sources=material_sources,
        )
        if saved:
            logger.info(
                f"saved material source records: "
                f"task_id={task_id}, count={len(material_sources)}"
            )
    except Exception as exc:
        # task_artifacts 自身已经按失败降级设计，这里仍保留最后一道隔离，
        # 防止未来实现调整或目录解析异常意外影响素材下载返回值。
        logger.warning(
            "failed to persist material source records: "
            f"task_id={task_id}, error={type(exc).__name__}, detail={exc}"
        )


def _get_tls_verify() -> bool:
    # 默认开启 TLS 证书校验，防止素材搜索和下载过程被中间人篡改。
    # 仅在企业代理、自签证书等明确需要的场景下，允许用户通过
    # `config.toml` 显式设置 `tls_verify = false` 临时关闭。
    tls_verify = config.app.get("tls_verify", True)
    if isinstance(tls_verify, str):
        tls_verify = tls_verify.strip().lower() not in ("0", "false", "no", "off")

    if not tls_verify:
        logger.warning(
            "TLS certificate verification is disabled by config.app.tls_verify=false. "
            "Only use this in trusted proxy environments."
        )

    return bool(tls_verify)


def get_api_key(cfg_key: str):
    api_keys = config.app.get(cfg_key)
    if not api_keys:
        raise ValueError(
            f"\n\n##### {cfg_key} is not set #####\n\n"
            f"Please set it in the config.toml file: {config.config_file}\n"
        )

    # if only one key is provided, return it
    if isinstance(api_keys, str):
        return api_keys

    global _api_key_counter
    with _api_key_lock:
        _api_key_counter += 1
        return api_keys[_api_key_counter % len(api_keys)]


def _redact_secret(message: str, secret: str) -> str:
    """
    对即将写入日志的异常文本做最小范围脱敏。

    requests 的连接异常可能包含完整请求 URL，而 Pixabay API Key 通过查询
    参数传递。这里同时替换原始值和 URL 编码值，既保留网络错误信息用于排查，
    又避免密钥进入日志文件。
    """
    safe_message = str(message)
    if not secret:
        return safe_message

    safe_message = safe_message.replace(secret, "***")
    encoded_secret = quote_plus(secret)
    if encoded_secret != secret:
        safe_message = safe_message.replace(encoded_secret, "***")
    return safe_message


def _redact_request_error(error: Exception, *secrets: str) -> str:
    """
    保留网络异常的可排查信息，同时移除 API Key 和代理凭据。

    直接只记录异常类型会丢失 DNS、证书、超时等关键上下文；直接记录原始异常
    又可能回显完整请求 URL。统一入口可以让三个素材供应商使用相同脱敏规则。
    """
    safe_message = str(error)
    for secret in secrets:
        safe_message = _redact_secret(safe_message, str(secret or ""))
    for proxy_url in config.proxy.values():
        safe_message = _redact_secret(safe_message, str(proxy_url))
    return safe_message


def _is_cloudflare_challenge(response: requests.Response) -> bool:
    """
    识别 Cloudflare 返回的 HTML Challenge，而不是把它当成 Pixabay JSON。

    Cloudflare 通常会设置 `cf-mitigated: challenge`；部分部署只返回带有
    "Just a moment" 或 challenge-platform 的 HTML，因此保留内容特征兜底。
    响应正文仅在内存中判断，不写入日志，避免记录无价值的大段 HTML。
    """
    headers = getattr(response, "headers", {}) or {}
    if str(headers.get("cf-mitigated", "")).lower() == "challenge":
        return True

    content_type = str(headers.get("content-type", "")).lower()
    if "text/html" not in content_type:
        return False

    body = str(getattr(response, "text", "")).lower()
    return "just a moment" in body or "/cdn-cgi/challenge-platform/" in body


def _matches_video_aspect(
    width: Any,
    height: Any,
    video_aspect: VideoAspect,
    *,
    is_vertical: Any = None,
) -> bool:
    """
    判断远端素材是否与目标画面方向一致。

    Pexels、Pixabay 和 Coverr 的响应字段并不统一，因此先使用宽高做可靠判断；
    Coverr 部分历史响应缺少尺寸时，再使用明确的 ``is_vertical`` 布尔值兜底。
    无法确认方向的素材直接跳过，避免竖屏任务混入横屏素材并在成片中产生黑边。
    """
    aspect = VideoAspect(video_aspect)
    try:
        normalized_width = int(float(width))
        normalized_height = int(float(height))
    except (TypeError, ValueError):
        normalized_width = 0
        normalized_height = 0

    if normalized_width > 0 and normalized_height > 0:
        if aspect == VideoAspect.portrait:
            return normalized_height > normalized_width
        if aspect == VideoAspect.landscape:
            return normalized_width > normalized_height
        return normalized_width == normalized_height

    if isinstance(is_vertical, bool) and aspect != VideoAspect.square:
        return is_vertical == (aspect == VideoAspect.portrait)
    return False


def _filter_materials_by_aspect(
    items: List[MaterialInfo],
    video_aspect: VideoAspect,
) -> List[MaterialInfo]:
    """
    对缓存结果再次校验方向。

    素材搜索缓存最长保留 24 小时，升级前写入的缓存可能包含方向不匹配的素材。
    在统一缓存入口过滤可以让修复立即生效，也能防御第三方 Provider 或旧缓存
    遗漏远端筛选。无法读取 rendition 尺寸的旧条目按未验证处理并跳过。
    """
    aspect = VideoAspect(video_aspect)
    if aspect == VideoAspect.square:
        # Pixabay 和 Coverr 很少提供原生方形素材。方形输出沿用既有行为，
        # 接受可用候选并交给视频合成阶段裁剪，避免升级后 1:1 任务无素材。
        return list(items)

    filtered_items = []
    for item in items:
        source_info = item.source_info if isinstance(item.source_info, dict) else {}
        rendition = source_info.get("rendition")
        rendition = rendition if isinstance(rendition, dict) else {}
        if _matches_video_aspect(
            rendition.get("width"),
            rendition.get("height"),
            aspect,
        ):
            filtered_items.append(item)
    return filtered_items


def search_videos_pexels(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    aspect = VideoAspect(video_aspect)
    video_orientation = aspect.name
    video_width, video_height = aspect.to_resolution()
    api_key = get_api_key("pexels_api_keys")
    headers = {
        "Authorization": api_key,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    }
    # Build URL
    params = {"query": search_term, "per_page": 20, "orientation": video_orientation}
    query_url = f"https://api.pexels.com/v1/videos/search?{urlencode(params)}"
    logger.info(f"searching videos on pexels: term={search_term!r}")

    try:
        r = requests.get(
            query_url,
            headers=headers,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(30, 60),
        )
        response = r.json()
        video_items = []
        if "videos" not in response:
            logger.error("pexels video search returned an unsupported response")
            return video_items
        videos = response["videos"]
        # loop through each video in the result
        for v in videos:
            duration = v["duration"]
            # check if video has desired minimum duration
            if duration < minimum_duration:
                continue
            video_files = v["video_files"]
            # loop through each url to determine the best quality
            for video in video_files:
                w = int(video["width"])
                h = int(video["height"])
                if (
                    _matches_video_aspect(w, h, aspect)
                    and w == video_width
                    and h == video_height
                ):
                    item = MaterialInfo()
                    item.provider = "pexels"
                    item.url = video["link"]
                    item.duration = duration
                    item.source_info = {
                        "provider": "pexels",
                        "search_term": search_term,
                        "asset_id": (
                            str(v.get("id")) if v.get("id") is not None else None
                        ),
                        "source_page": _safe_public_url(v.get("url")),
                        "creator": _creator_info(v.get("user")),
                        "rendition": {
                            "id": (
                                str(video.get("id"))
                                if video.get("id") is not None
                                else None
                            ),
                            "width": w,
                            "height": h,
                        },
                    }
                    video_items.append(item)
                    break
        return video_items
    except Exception as e:
        logger.error(
            "pexels video search failed: "
            f"error={type(e).__name__}, detail={_redact_request_error(e, api_key)}"
        )

    return []


def search_videos_pixabay(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    aspect = VideoAspect(video_aspect)

    video_width, video_height = aspect.to_resolution()

    api_key = get_api_key("pixabay_api_keys")
    # Build URL
    params = {
        "q": search_term,
        "video_type": "all",  # Accepted values: "all", "film", "animation"
        "per_page": 50,
        "key": api_key,
    }
    query_url = f"https://pixabay.com/api/videos/?{urlencode(params)}"
    logger.info(
        f"searching videos on pixabay: term={search_term!r}, "
        f"proxy_enabled={bool(config.proxy)}"
    )

    try:
        r = requests.get(
            query_url, proxies=config.proxy, verify=_get_tls_verify(), timeout=(30, 60)
        )
        status_code = int(getattr(r, "status_code", 200))
        headers = getattr(r, "headers", {}) or {}
        content_type = str(headers.get("content-type", ""))
        retry_after = headers.get("retry-after")
        cf_ray = headers.get("cf-ray")

        if _is_cloudflare_challenge(r):
            logger.error(
                "pixabay search was blocked by a Cloudflare challenge: "
                f"status={status_code}, cf_ray={cf_ray or 'unknown'}. "
                "Check the server network or proxy, or use Pexels/Coverr instead."
            )
            return []

        if status_code == 429:
            logger.error(
                "pixabay API rate limit exceeded: "
                f"status=429, retry_after={retry_after or 'unknown'}"
            )
            return []

        if status_code >= 400:
            logger.error(
                "pixabay search request failed: "
                f"status={status_code}, content_type={content_type or 'unknown'}"
            )
            return []

        try:
            response = r.json()
        except ValueError:
            logger.error(
                "pixabay returned an unexpected non-JSON response: "
                f"status={status_code}, content_type={content_type or 'unknown'}"
            )
            return []

        video_items = []
        if "hits" not in response:
            logger.error("pixabay video search returned an unsupported response")
            return video_items
        videos = response["hits"]
        # loop through each video in the result
        for v in videos:
            duration = v["duration"]
            # check if video has desired minimum duration
            if duration < minimum_duration:
                continue
            video_files = v["videos"]
            # loop through each url to determine the best quality
            for video_type in video_files:
                video = video_files[video_type]
                try:
                    w = int(video["width"])
                    h = int(video["height"])
                except (KeyError, TypeError, ValueError):
                    continue
                # Pixabay 很少返回原生方形视频；1:1 输出继续接受满足分辨率的
                # 候选并由合成阶段裁剪。横竖屏则必须严格匹配目标方向。
                orientation_matches = aspect == VideoAspect.square or (
                    _matches_video_aspect(w, h, aspect)
                )
                if orientation_matches and w >= video_width:
                    item = MaterialInfo()
                    item.provider = "pixabay"
                    item.url = video["url"]
                    item.duration = duration
                    item.source_info = {
                        "provider": "pixabay",
                        "search_term": search_term,
                        "asset_id": (
                            str(v.get("id")) if v.get("id") is not None else None
                        ),
                        "source_page": _safe_public_url(v.get("pageURL")),
                        "creator": _creator_info(
                            {
                                "id": v.get("user_id"),
                                "name": v.get("user"),
                            }
                        ),
                        "rendition": {
                            "id": video_type,
                            "width": w,
                            "height": video.get("height"),
                        },
                    }
                    video_items.append(item)
                    break
        return video_items
    except Exception as e:
        error_message = _redact_request_error(e, api_key)
        logger.error(
            "pixabay search request failed: "
            f"error={type(e).__name__}, detail={error_message}"
        )

    return []


def search_videos_coverr(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    """
    Coverr (https://coverr.co) - free HD/4K stock videos,
    subject to Coverr license terms (https://coverr.co/license).

    Coverr API notes (based on official docs at api.coverr.co/docs/):
      - 鉴权: Authorization: Bearer <api_key>
      - 搜索端点: GET /videos?query=...,响应结构 {"hits": [...], ...}
      - 加 ?urls=true 在搜索响应里直接返回 mp4 直链
      - URL 是 signed JWT(绑定 API key,无过期时间)
      - Coverr 支持通过 filter=is_vertical:true/false 筛选横竖屏素材；
        响应返回后仍根据 max_width/max_height 或 is_vertical 做本地校验
      - duration 字段同时存在 number 和 string 两种形态,本函数都接受

    本函数使用 urls.mp4_download 字段作为下载地址 —— 按 Coverr 官方文档
    (https://api.coverr.co/docs/videos/#download-a-video) 的说法,
    GET 这个 URL 本身就被 Coverr 当作一次合法的 download 事件计入统计,
    无需再调用 PATCH /videos/:id/stats/downloads。
    """
    aspect = VideoAspect(video_aspect)
    api_key = get_api_key("coverr_api_keys")
    headers = {"Authorization": f"Bearer {api_key}"}
    params = {
        "query": search_term,
        "page_size": 20,
        "urls": "true",
        "sort": "popular",
    }
    # 服务端方向筛选可以直接从完整搜索结果中返回目标素材，避免先取热门结果再
    # 本地过滤导致竖屏候选为空。方形素材没有对应布尔条件，继续依赖本地宽高校验。
    if aspect == VideoAspect.portrait:
        params["filter"] = "is_vertical:true"
    elif aspect == VideoAspect.landscape:
        params["filter"] = "is_vertical:false"
    query_url = f"https://api.coverr.co/videos?{urlencode(params)}"
    logger.info(f"searching videos on coverr: term={search_term!r}")

    try:
        r = requests.get(
            query_url,
            headers=headers,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(30, 60),
        )
        response = r.json()
        video_items: List[MaterialInfo] = []

        if not isinstance(response, dict) or "hits" not in response:
            logger.error("coverr video search returned an unsupported response")
            return video_items

        for v in response["hits"]:
            # duration 在不同响应里可能是 number(11.625) 或 string("10.500000")
            try:
                duration = int(float(v.get("duration") or 0))
            except (TypeError, ValueError):
                continue
            if duration < minimum_duration:
                continue

            video_id = v.get("id")
            mp4_download_url = (v.get("urls") or {}).get("mp4_download")
            if not video_id or not mp4_download_url:
                continue
            if aspect != VideoAspect.square and not _matches_video_aspect(
                v.get("max_width"),
                v.get("max_height"),
                aspect,
                is_vertical=v.get("is_vertical"),
            ):
                continue

            item = MaterialInfo()
            item.provider = "coverr"
            item.url = mp4_download_url
            item.duration = duration
            item.source_info = {
                "provider": "coverr",
                "search_term": search_term,
                "asset_id": str(video_id),
                "source_page": _safe_public_url(v.get("canonical_url") or v.get("url")),
                "creator": _creator_info(v.get("creator") or v.get("author")),
                "rendition": {
                    "id": "mp4_download",
                    "width": v.get("max_width"),
                    "height": v.get("max_height"),
                },
            }
            video_items.append(item)
        return video_items
    except Exception as e:
        logger.error(
            "coverr video search failed: "
            f"error={type(e).__name__}, detail={_redact_request_error(e, api_key)}"
        )

    return []


def search_videos_youtube(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    """
    Search YouTube via yt_dlp's ytsearch (flat metadata only — no download).

    Unlike Pexels/Pixabay/Coverr (which filter by portrait aspect at search
    time), YouTube results are NOT aspect-filtered here. Landscape videos are
    accepted and handled by the smart reframe pipeline (BAGIAN C). This lets
    YouTube contribute landscape footage that would otherwise be excluded,
    dramatically expanding the usable candidate pool.

    yt_dlp search + metadata extraction works WITHOUT authentication. Video
    *download* requires cookies (see ``save_video_youtube``).

    License provenance: YouTube's license field is only available on full
    extraction (blocked without auth). We mark status as ``"license_unknown"``
    and rely on the caller to treat it accordingly (fail-clean if license is
    a hard requirement).
    """
    if yt_dlp is None:
        logger.error("yt_dlp is not installed; YouTube provider unavailable")
        return []

    aspect = VideoAspect(video_aspect)

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,      # metadata only, no download
        "skip_download": True,
        "simulate": True,
        "force_generic_extractor": False,
    }

    cookies_file = config.app.get("youtube_cookies_file", "").strip()
    if cookies_file and os.path.exists(cookies_file):
        ydl_opts["cookiefile"] = cookies_file

    query = f"ytsearch:{search_term}"
    logger.info(f"searching videos on youtube: term={search_term!r}")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(query, download=False)
    except Exception as e:
        logger.error(
            "youtube video search failed: "
            f"error={type(e).__name__}, detail={str(e)[:200]}"
        )
        return []

    entries = result.get("entries", []) if isinstance(result, dict) else []
    if not entries:
        return []

    video_items: List[MaterialInfo] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue

        duration = entry.get("duration")
        if duration is None:
            # Live streams or entries without duration — skip (can't fit scene)
            continue
        try:
            duration = int(float(duration))
        except (TypeError, ValueError):
            continue
        if duration < minimum_duration:
            continue

        video_id = entry.get("id") or ""
        title = entry.get("title") or ""
        channel = entry.get("channel") or entry.get("uploader") or ""
        url = entry.get("weburl") or entry.get("url") or ""
        if not url.startswith("http"):
            url = f"https://www.youtube.com/watch?v={video_id}"

        # Try to extract resolution from formats
        rendition = None
        formats = entry.get("formats") or []
        if formats:
            best = max(formats, key=lambda f: f.get("height", 0) or 0)
            rendition = {
                "id": best.get("format_id"),
                "width": best.get("width"),
                "height": best.get("height"),
            }

        item = MaterialInfo()
        item.provider = "youtube"
        item.url = url
        item.duration = duration
        item.source_info = {
            "provider": "youtube",
            "search_term": search_term,
            "asset_id": str(video_id) if video_id else None,
            "source_page": url,
            "title": title,
            "channel": channel,
            "license_status": "license_unknown",
            "rendition": rendition,
        }
        video_items.append(item)

    return video_items


# WaveSpeed AI (https://wavespeed.ai) 通过文生视频模型按脚本关键词直接生成素材，
# 与三个库存素材源共用 MaterialInfo 结果结构和后续下载、剪辑流程。
WAVESPEED_API_BASE_URL = "https://api.wavespeed.ai/api/v3"
WAVESPEED_DEFAULT_T2V_MODEL = "bytedance/seedance-2.0-fast/text-to-video"
WAVESPEED_POLL_INTERVAL_SECONDS = 2.0
WAVESPEED_RUN_TIMEOUT_SECONDS = 600.0
# 默认模型 bytedance/seedance-2.0-fast/text-to-video 只接受 4-15 秒；超出
# 范围的请求会被 API 直接拒绝。WebUI 默认片段时长是 3 秒，因此必须在提交
# 前收敛到模型支持区间，多出的时长由现有剪辑流程按片段时长裁掉。
WAVESPEED_MIN_DURATION_SECONDS = 4
WAVESPEED_MAX_DURATION_SECONDS = 15
# 三个失败态语义不同（模型报错 / 用户取消 / 平台超时），但对素材流程都意味着
# 本关键词没有产物，统一按空结果处理，交给上层跳过该片段继续生成。
WAVESPEED_FAILURE_STATUSES = frozenset({"failed", "cancelled", "timeout"})
# 与 WaveSpeed 官方 Python SDK / n8n 节点保持同一口径：429 与 5xx 属于临时
# 故障，值得有限次退避重试；4xx 是明确的客户端错误，快速失败。
WAVESPEED_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
# 单次轮询允许的连续临时失败次数。一次不走运的 GET 不能让已经计费的任务失联。
WAVESPEED_MAX_POLL_RETRIES = 5
# 线性退避基数，第 n 次重试等待 base * n 秒。
WAVESPEED_RETRY_BASE_SECONDS = 1.0
# 产物下载失败时对同一个签名地址的重试次数。素材已经付费生成，优先重试原
# 地址，不能因为一次下载抖动就重新提交一次付费生成任务。
WAVESPEED_MAX_DOWNLOAD_RETRIES = 2


class WaveSpeedUnconfirmedTaskError(RuntimeError):
    """
    付费生成任务已提交，但最终状态无法在本地确认。

    这类异常绝不等价于“该任务失败、可以重来”：远端任务可能仍在运行或已经
    完成并计费。素材流程必须就此停止，不再为后续关键词提交新的付费任务，
    并把已提交的 prediction id 留在日志中供人工找回。
    """

    def __init__(self, message: str, prediction_id: str = ""):
        super().__init__(message)
        self.prediction_id = prediction_id


def _wavespeed_status_code(response: Any) -> int:
    """读取响应状态码；测试替身或异常对象缺少该字段时按 200 处理。"""
    try:
        return int(getattr(response, "status_code", 200))
    except (TypeError, ValueError):
        return 200


def _is_wavespeed_retryable_error(error: Exception) -> bool:
    """
    判断轮询异常是否值得重试。

    连接、超时一类网络异常没有状态码，按临时故障处理；带状态码的响应只在
    429 和 5xx 时重试，与官方 SDK 的重试集合保持一致。
    """
    if isinstance(
        error,
        (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
        ),
    ):
        return True
    response = getattr(error, "response", None)
    if response is not None:
        return _wavespeed_status_code(response) in WAVESPEED_RETRYABLE_STATUS_CODES
    return False


def _wavespeed_duration_bounds() -> tuple[int, int]:
    """
    返回当前模型支持的生成时长区间（秒）。

    默认区间对应默认 Seedance 模型；用户切换到其它文生视频模型时，可以在
    配置中同步调整区间。任何异常配置都退回默认值，并保证 min <= max，
    避免把用户输入变成必然失败的远端请求。
    """

    def read_bound(key: str, fallback: int) -> int:
        try:
            value = int(config.app.get(key, fallback))
        except (TypeError, ValueError):
            return fallback
        return value if value >= 1 else fallback

    min_duration = read_bound("wavespeed_min_duration", WAVESPEED_MIN_DURATION_SECONDS)
    max_duration = read_bound("wavespeed_max_duration", WAVESPEED_MAX_DURATION_SECONDS)
    return min_duration, max(max_duration, min_duration)


def generate_videos_wavespeed(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    """
    用 WaveSpeed 文生视频模型为一个脚本关键词生成一段素材。

    与库存素材源的 search_videos_* 保持同一签名和空列表失败约定，
    使其可以直接接入 ``download_videos`` 的通用下载与时长核算流程。
    ``minimum_duration`` 在生成语境下就是目标片段时长（秒）。
    """
    aspect = VideoAspect(video_aspect)
    video_width, video_height = aspect.to_resolution()
    api_key = get_api_key("wavespeed_api_keys")
    model_id = (
        str(
            config.app.get("wavespeed_text_to_video_model", "")
            or WAVESPEED_DEFAULT_T2V_MODEL
        )
        .strip()
        .strip("/")
    )
    headers = {"Authorization": f"Bearer {api_key}"}
    requested_duration = max(int(minimum_duration), 1)
    min_duration, max_duration = _wavespeed_duration_bounds()
    duration = min(max(requested_duration, min_duration), max_duration)
    if duration != requested_duration:
        # 生成比请求更长不会影响成片：剪辑流程仍按片段时长裁剪；生成比请求
        # 更短的情况只发生在请求超过模型上限时，此时也只能收敛到上限。
        logger.info(
            f"wavespeed clip duration clamped to model-supported range: "
            f"requested={requested_duration}s, using={duration}s "
            f"(supported {min_duration}-{max_duration}s)"
        )
    payload = {
        "prompt": search_term,
        "aspect_ratio": aspect.value,
        "duration": duration,
    }
    logger.info(
        f"generating video on wavespeed: model={model_id}, "
        f"term={search_term!r}, duration={duration}s"
    )

    # 提交 POST 绝不自动重试：请求可能已经在远端创建了付费任务，重发会造成
    # 重复生成和重复扣费（与官方 SDK 的 submission 策略一致）。
    try:
        submit_response = requests.post(
            f"{WAVESPEED_API_BASE_URL}/{model_id}",
            json=payload,
            headers=headers,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(30, 60),
        )
    except Exception as e:
        # 没有收到响应并不代表任务没有创建。此时状态不明，必须终止整个生成
        # 流程，而不是继续为下一个关键词提交新的付费任务。
        raise WaveSpeedUnconfirmedTaskError(
            "wavespeed submission did not return a response, the task may "
            "already exist remotely: "
            f"error={type(e).__name__}, detail={_redact_request_error(e, api_key)}"
        ) from e

    submit_status = _wavespeed_status_code(submit_response)
    if submit_status >= 500:
        # 5xx 可能发生在任务创建之后，无法判断是否已经计费。
        raise WaveSpeedUnconfirmedTaskError(
            f"wavespeed submission failed with HTTP {submit_status}, "
            "the task may already exist remotely"
        )
    try:
        submit_body = submit_response.json()
    except Exception as e:
        raise WaveSpeedUnconfirmedTaskError(
            "wavespeed submission returned an unreadable response, the task "
            f"may already exist remotely: error={type(e).__name__}"
        ) from e

    submit_data = submit_body.get("data") if isinstance(submit_body, dict) else None
    if not isinstance(submit_body, dict) or submit_body.get("code") != 200:
        # 4xx 与业务错误码是明确的拒绝，远端没有创建任务，也就不存在重复
        # 计费风险，按现有素材源约定返回空结果并继续。
        logger.error(
            "wavespeed video generation request rejected: "
            f"http_status={submit_status}, "
            f"code={submit_body.get('code') if isinstance(submit_body, dict) else None}, "
            f"detail={_redact_secret(str((submit_body or {}).get('message') or ''), api_key)}"
        )
        return []
    prediction_id = (
        str(submit_data.get("id") or "") if isinstance(submit_data, dict) else ""
    )
    if not prediction_id:
        # 提交被接受但没拿到 ID：任务可能已经存在却无法追踪，不能继续下单。
        raise WaveSpeedUnconfirmedTaskError(
            "wavespeed accepted the submission without returning a prediction id"
        )
    # 生成任务提交成功即产生远端计费副作用，先落日志记录任务 ID，
    # 即使后续轮询失败，用户仍能凭 ID 在 WaveSpeed 控制台找回产物。
    logger.info(f"wavespeed prediction created: id={prediction_id}")

    result_data = _wait_for_wavespeed_prediction(
        prediction_id=prediction_id,
        headers=headers,
        api_key=api_key,
    )
    if result_data is None:
        return []

    try:
        video_items = []
        outputs = result_data.get("outputs")
        for output in outputs if isinstance(outputs, list) else []:
            # 产物 URL 是带签名的临时下载地址，必须整体保留（不能剥离查询参
            # 数），因此不写入 source_info，只用于随后的立即下载。
            if not isinstance(output, str) or not output.startswith(
                ("http://", "https://")
            ):
                continue
            item = MaterialInfo()
            item.provider = "wavespeed"
            item.url = output
            item.duration = duration
            item.source_info = {
                "provider": "wavespeed",
                "search_term": search_term,
                "asset_id": prediction_id,
                "rendition": {
                    "id": None,
                    "width": video_width,
                    "height": video_height,
                },
            }
            video_items.append(item)
        if not video_items:
            logger.error(
                "wavespeed prediction completed without downloadable outputs: "
                f"id={prediction_id}"
            )
        return video_items
    except Exception as e:
        # 产物已经生成并计费，这里的异常只可能来自本地解析。记录后按空结果
        # 返回，让上层跳过该片段，但任务状态本身是确定的，可以继续后续片段。
        logger.error(
            "wavespeed output parsing failed: "
            f"id={prediction_id}, error={type(e).__name__}, "
            f"detail={_redact_request_error(e, api_key)}"
        )

    return []


def _wait_for_wavespeed_prediction(
    *,
    prediction_id: str,
    headers: dict,
    api_key: str,
) -> dict | None:
    """
    轮询同一个 prediction id 直到出现确定结果。

    返回 ``completed`` 的 data；远端明确失败（failed / cancelled / timeout）
    时返回 None，表示该任务已经结束、可以安全地继续后续片段。临时故障按
    线性退避重试同一个 ID，绝不重新提交任务；状态始终无法确认时抛出
    :class:`WaveSpeedUnconfirmedTaskError`，由调用方终止整个生成流程。
    """
    deadline = time.monotonic() + WAVESPEED_RUN_TIMEOUT_SECONDS
    consecutive_failures = 0
    while True:
        try:
            response = requests.get(
                f"{WAVESPEED_API_BASE_URL}/predictions/{prediction_id}/result",
                headers=headers,
                proxies=config.proxy,
                verify=_get_tls_verify(),
                timeout=(30, 60),
            )
            status_code = _wavespeed_status_code(response)
            if status_code in WAVESPEED_RETRYABLE_STATUS_CODES:
                raise requests.exceptions.HTTPError(
                    f"HTTP {status_code}", response=response
                )
            result_body = response.json()
            result_data = (
                result_body.get("data") if isinstance(result_body, dict) else None
            )
            if not isinstance(result_body, dict) or result_body.get("code") != 200:
                # 轮询被明确拒绝（如 4xx）时任务状态仍然未知：任务已经提交，
                # 只是本地查不到结果，同样不能继续提交新的付费任务。
                raise WaveSpeedUnconfirmedTaskError(
                    "wavespeed prediction status is unknown: "
                    f"http_status={status_code}, "
                    f"code={result_body.get('code') if isinstance(result_body, dict) else None}, "
                    f"detail={_redact_secret(str((result_body or {}).get('message') or ''), api_key)}",
                    prediction_id=prediction_id,
                )
            if not isinstance(result_data, dict):
                raise WaveSpeedUnconfirmedTaskError(
                    "wavespeed prediction result payload is malformed",
                    prediction_id=prediction_id,
                )
        except WaveSpeedUnconfirmedTaskError:
            raise
        except Exception as e:
            if not _is_wavespeed_retryable_error(e):
                raise WaveSpeedUnconfirmedTaskError(
                    "wavespeed prediction polling failed and the task state is "
                    f"unknown: error={type(e).__name__}, "
                    f"detail={_redact_request_error(e, api_key)}",
                    prediction_id=prediction_id,
                ) from e
            consecutive_failures += 1
            if consecutive_failures > WAVESPEED_MAX_POLL_RETRIES:
                raise WaveSpeedUnconfirmedTaskError(
                    "wavespeed prediction polling failed after "
                    f"{WAVESPEED_MAX_POLL_RETRIES + 1} attempts, the task may "
                    "still be running remotely: "
                    f"error={type(e).__name__}, "
                    f"detail={_redact_request_error(e, api_key)}",
                    prediction_id=prediction_id,
                ) from e
            delay = WAVESPEED_RETRY_BASE_SECONDS * consecutive_failures
            logger.warning(
                "wavespeed prediction polling hit a transient error, retry the "
                f"same task: id={prediction_id}, "
                f"attempt={consecutive_failures}/{WAVESPEED_MAX_POLL_RETRIES}, "
                f"error={type(e).__name__}, retry_in={delay:.1f}s"
            )
            time.sleep(delay)
            continue

        # 拿到一次有效响应就重置计数，只有连续失败才消耗重试额度。
        consecutive_failures = 0
        status = str(result_data.get("status") or "")
        if status == "completed":
            return result_data
        if status in WAVESPEED_FAILURE_STATUSES:
            logger.error(
                "wavespeed prediction did not produce a video: "
                f"id={prediction_id}, status={status}, "
                f"detail={_redact_secret(str(result_data.get('error') or ''), api_key)}"
            )
            return None
        if time.monotonic() > deadline:
            # 远端任务仍在执行，本地无法确认最终状态，必须停止继续下单。
            raise WaveSpeedUnconfirmedTaskError(
                f"wavespeed prediction is still {status or 'pending'} after "
                f"{WAVESPEED_RUN_TIMEOUT_SECONDS:.0f}s of local waiting",
                prediction_id=prediction_id,
            )
        time.sleep(WAVESPEED_POLL_INTERVAL_SECONDS)


def _save_wavespeed_video_with_retry(video_url: str, save_dir: str) -> str:
    """
    下载已经付费生成的产物，失败时优先重试同一个地址。

    重新生成一次远端任务的代价是再付一次费，所以下载抖动必须先在原地址上
    做有限次退避重试，重试耗尽才放弃该片段。
    """
    for attempt in range(WAVESPEED_MAX_DOWNLOAD_RETRIES + 1):
        try:
            saved_video_path = save_video(video_url=video_url, save_dir=save_dir)
            if saved_video_path:
                return saved_video_path
            failure_detail = "empty result"
        except Exception as e:
            failure_detail = (
                f"error={type(e).__name__}, "
                f"detail={_redact_request_error(e, video_url)}"
            )
        if attempt >= WAVESPEED_MAX_DOWNLOAD_RETRIES:
            break
        delay = WAVESPEED_RETRY_BASE_SECONDS * (attempt + 1)
        logger.warning(
            "failed to download generated video, retry the same url: "
            f"attempt={attempt + 1}/{WAVESPEED_MAX_DOWNLOAD_RETRIES}, "
            f"{failure_detail}, retry_in={delay:.1f}s"
        )
        time.sleep(delay)
    logger.error(
        "failed to download generated video after "
        f"{WAVESPEED_MAX_DOWNLOAD_RETRIES + 1} attempts: {failure_detail}"
    )
    return ""


def save_video(video_url: str, save_dir: str = "") -> str:
    if not save_dir:
        save_dir = utils.storage_dir("cache_videos")

    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    url_without_query = video_url.split("?")[0]
    url_hash = utils.md5(url_without_query)
    video_id = f"vid-{url_hash}"
    video_path = f"{save_dir}/{video_id}.mp4"

    # if video already exists, return the path
    if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
        logger.info(f"video already exists: {video_path}")
        return video_path

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }

    # if video does not exist, download it
    with open(video_path, "wb") as f:
        f.write(
            requests.get(
                video_url,
                headers=headers,
                proxies=config.proxy,
                verify=_get_tls_verify(),
                timeout=(60, 240),
            ).content
        )

    if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
        clip = None
        try:
            clip = VideoFileClip(video_path)
            duration = clip.duration
            fps = clip.fps
            if duration > 0 and fps > 0:
                return video_path
        except Exception as e:
            logger.warning(f"invalid video file: {video_path} => {str(e)}")
            try:
                os.remove(video_path)
            except Exception as remove_error:
                logger.warning(
                    f"failed to remove invalid video file: {video_path}, error: {str(remove_error)}"
                )
        finally:
            if clip is not None:
                try:
                    clip.close()
                except Exception as close_error:
                    logger.warning(
                        f"failed to close video clip: {video_path}, error: {str(close_error)}"
                    )
    return ""


# ─── YouTube download + universal resolver helpers ──────────────────────────

# Minimum resolution below which a clip is considered too low-quality for a
# 9:16 render after reframing.  Clips at or above this threshold have enough
# pixels to fill 1080×1920 (even after scale-to-cover + crop).
_MATERIAL_MIN_WIDTH = 480
_MATERIAL_MIN_HEIGHT = 480

# ─── Output-aware quality gate (Phase 10F) ────────────────────────────────────
#
# Minimum effective source dimension (in pixels) that must remain after the
# actual 9:16 scale-to-cover + crop transformation used by combine_videos().
# This replaces the blunt ``w < 480 OR h < 480'' check for the post-download
# quality gate, allowing e.g. 854×480 landscape to pass when its *effective*
# source resolution (270 after scale-to-cover) comfortably exceeds 250, while
# still rejecting 640×360 (effective 202) and 320×180 (effective 101).
#
# The threshold 250 was established by the Phase 10E mathematical model and
# approved by the Phase 10F design spike.
#
# NOTE: ``_MATERIAL_MIN_WIDTH`` / ``_MATERIAL_MIN_HEIGHT`` are intentionally
# retained — they are still used as a pre-download filter in rank_videos()
# (see line ~1380).  They are NOT silently removed.
_EFFECTIVE_MIN_DIMENSION = 250.0


def _validate_reframe_resolution(
    width: int,
    height: int,
    target_width: int,
    target_height: int,
    min_effective_dimension: float = _EFFECTIVE_MIN_DIMENSION,
) -> bool:
    """Determine whether a source resolution is sufficient for the actual
    9:16 target output *after* the pipeline's proportional scale-to-cover + crop.

    This implements the same mathematical model used by ``combine_videos()``
    in ``app/services/video.py`` (scale-to-cover via moviepy ``.resized()``
    followed by center-crop).  Instead of requiring both source dimensions to
    be ≥ 480, it checks the *effective* source pixels that survive the
    transformation.

    Algorithm (mirrors video.py:676-700):

        src_ratio   = width  / height
        target_ratio = target_width / target_height

        if src_ratio > target_ratio:
            # source is wider than target → scale by height
            scale = target_height / height
        else:
            # source is taller/same → scale by width
            scale = target_width / width

        effective_src_w = target_width  / scale
        effective_src_h = target_height / scale
        effective_min   = min(effective_src_w, effective_src_h)

    Accept if ``effective_min >= min_effective_dimension``.

    Parameters
    ----------
    width, height :
        Source clip dimensions (pixels).  Must be positive.
    target_width, target_height :
        Target output dimensions, resolved from ``VideoAspect.to_resolution()``
        by the caller — never hard-coded inside this helper.
    min_effective_dimension :
        Floor for the smallest effective source dimension (default 250.0).
    """
    if width <= 0 or height <= 0:
        return False
    if target_width <= 0 or target_height <= 0:
        return False

    src_ratio = width / height
    target_ratio = target_width / target_height

    if src_ratio > target_ratio:
        # Source is wider than target → constrained by height
        scale = target_height / height
    else:
        # Source is taller or equal → constrained by width
        scale = target_width / width

    effective_src_w = target_width / scale
    effective_src_h = target_height / scale
    effective_min = min(effective_src_w, effective_src_h)

    return effective_min >= min_effective_dimension


# Hosts that identify a YouTube video resource (subdomain prefixes are stripped
# inside the helper).  Only these hosts are canonicalized; everything else is
# treated as a non-YouTube URL and falls back to the legacy URL-based key.
_YOUTUBE_HOSTS = {
    "youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
    "music.youtube.com",
}

# YouTube video IDs are exactly 11 characters from this alphabet.  Validating
# the ID (rather than trusting any query value) keeps canonicalization safe for
# malformed/unsupported URLs.
_YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _youtube_video_identity(video_url: str) -> Optional[str]:
    """Return a canonical, collision-free identity for a YouTube video URL.

    The previous cache key used ``video_url.split("?")[0]``, which collapsed
    every ``https://www.youtube.com/watch?v=<ID>`` URL to the identical string
    ``https://www.youtube.com/watch`` — so distinct videos shared one cache file
    (Phase 10H.1 defect).  We now canonicalize by the YouTube *video ID* (the
    only parameter that determines identity) and ignore tracking/query noise
    (``feature=``, ``t=``, ``utm_*``, …).

    Supported, MPT-relevant URL forms:
      * ``https://www.youtube.com/watch?v=<ID>[&t=…&feature=…]``
      * ``https://youtu.be/<ID>[?…]``
      * ``https://www.youtube.com/shorts/<ID>[?…]``
      * ``m.``/``www.``/``music.`` subdomains and ``youtube-nocookie.com``
      * (tolerated, not used by MPT) ``/embed/<ID>``

    Only the 11-char video ID affects identity; all other query parameters are
    ignored.  Returns ``None`` for non-YouTube or malformed URLs so the caller
    can fall back safely (no unsafe collision).  The returned value is a stable
    identity token (e.g. ``"yt:<ID>"``) used to derive the deterministic cache
    filename — it is NOT a full URL.
    """
    if not video_url:
        return None
    try:
        parsed = urlparse(video_url)
    except Exception:
        return None
    host = (parsed.netloc or "").lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m."):
        host = host[2:]
    if host not in _YOUTUBE_HOSTS:
        return None

    if host == "youtu.be":
        vid = parsed.path.strip("/").split("/")[0]
    elif "/shorts/" in parsed.path:
        vid = parsed.path.split("/shorts/")[-1].split("/")[0]
    elif "/embed/" in parsed.path:
        vid = parsed.path.split("/embed/")[-1].split("/")[0]
    else:
        qs = parse_qs(parsed.query)
        vid = (qs.get("v") or [""])[0]

    if not vid or not _YOUTUBE_ID_RE.fullmatch(vid):
        return None
    return f"yt:{vid}"


def save_video_youtube(video_url: str, save_dir: str = "") -> str:
    """Download a YouTube video via yt_dlp.

    Uses the ``cookiefile`` from ``config.app['youtube_cookies_file']`` when
    configured.  Without cookies, YouTube blocks the download with HTTP 403
    (bot detection) — in that case the function returns ``""`` (fail-clean),
    allowing the caller to try the next provider.

    Returns the local file path on success, ``""`` on failure.
    """
    if yt_dlp is None:
        logger.error("yt_dlp is not installed; YouTube download unavailable")
        return ""

    if not save_dir:
        save_dir = utils.storage_dir("cache_videos")
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    # Cache filename is derived from a canonical YouTube video identity so that
    # distinct videos never collide in cache_videos/ (Phase 10H.1).  Equivalent
    # supported URLs for the same video resolve to the same identity; non-YouTube
    # or malformed URLs fall back to the prior URL-based key for safety.
    identity = _youtube_video_identity(video_url)
    if identity:
        url_hash = utils.md5(identity)
    else:
        url_hash = utils.md5(video_url.split("?")[0])
    video_id = f"vid-{url_hash}"
    video_path = f"{save_dir}/{video_id}.mp4"

    if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
        logger.info(f"youtube video already exists: {video_path}")
        return video_path

    ydl_opts = {
        "format": "best[ext=mp4][height<=720]",
        "outtmpl": video_path,
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
    }

    cookies_file = config.app.get("youtube_cookies_file", "").strip()
    if cookies_file and os.path.exists(cookies_file):
        ydl_opts["cookiefile"] = cookies_file

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
    except yt_dlp.utils.DownloadError as e:
        if "403" in str(e) or "Sign in" in str(e):
            logger.error(
                f"youtube download blocked (403/bot detection) for {video_url}; "
                "set youtube_cookies_file in config.toml for authenticated downloads"
            )
        else:
            logger.error(
                f"youtube download failed: error={type(e).__name__}, "
                f"detail={str(e)[:200]}"
            )
        return ""
    except Exception as e:
        logger.error(
            f"youtube download failed: error={type(e).__name__}, "
            f"detail={str(e)[:200]}"
        )
        return ""

    if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
        return video_path
    return ""


def _validate_downloaded_clip(video_path: str,
                               min_duration: int = 0,
                               video_aspect: VideoAspect = VideoAspect.portrait) -> bool:
    """Quality-gate: verify a downloaded clip is playable and meets minimum
    requirements.  Uses ffprobe + moviepy to check:

    * File exists and size > 0
    * Duration > 0 and fps > 0
    * Source resolution is sufficient to produce the target 9:16 output
      without excessive pixelation, using the output-aware effective-resolution
      model (Phase 10F).  See ``_validate_reframe_resolution()``.

    The pre-download filter in ``rank_videos()`` still uses
    ``_MATERIAL_MIN_WIDTH`` / ``_MATERIAL_MIN_HEIGHT`` as a coarse safety net.

    Parameters
    ----------
    video_path :
        Local path to the downloaded clip.
    min_duration :
        Minimum acceptable duration in seconds (0 = no duration check).
    video_aspect :
        Target VideoAspect (``VideoAspect.portrait``, ``.landscape``, or
        ``.square``).  Default is ``portrait`` (1080×1920) — the canonical
        TikTok/Reels target.

    Returns True if the clip passes all checks.
    """
    if not video_path or not os.path.exists(video_path):
        return False
    if os.path.getsize(video_path) <= 1024:
        return False

    try:
        clip = VideoFileClip(video_path)
        duration = clip.duration
        fps = clip.fps
        w, h = clip.size
        clip.close()
    except Exception as e:
        logger.warning(f"quality gate: invalid video {video_path}: {e}")
        return False

    if duration <= 0 or fps <= 0:
        logger.warning(f"quality gate: zero duration/fps for {video_path}")
        return False

    # Phase 10F: output-aware effective-resolution gate.
    # Resolve canonical target dimensions from VideoAspect (not hard-coded).
    target_w, target_h = video_aspect.to_resolution()
    if not _validate_reframe_resolution(w, h, target_w, target_h):
        logger.warning(
            f"quality gate: source resolution {w}x{h} yields effective "
            f"source dimension below {_EFFECTIVE_MIN_DIMENSION} "
            f"for target {target_w}x{target_h} — {video_path}"
        )
        return False

    if min_duration > 0 and duration < min_duration:
        logger.warning(
            f"quality gate: duration {duration:.1f}s below minimum {min_duration}s "
            f"for {video_path}"
        )
        return False

    return True


def _score_candidate(item: MaterialInfo, search_term: str,
                     minimum_duration: int, video_aspect: VideoAspect) -> float:
    """Score a material candidate: higher = better.

    Scoring factors (normalized to ~0–1 range):
      * Duration match (0.3 weight): closer to or above minimum_duration.
      * Relevance (0.4 weight): keyword overlap between search_term and item
        title/description (case-insensitive token overlap).
      * Resolution (0.3 weight): pixel count, higher is better for reframing.
    """
    score = 0.0
    info = item.source_info or {}

    # Duration match: full points if >= minimum_duration, partial if close
    dur = item.duration or 0
    if dur >= minimum_duration:
        score += 0.3
    elif dur >= minimum_duration * 0.8:
        score += 0.15

    # Relevance: token overlap
    query_tokens = set(search_term.lower().split())
    title = str(info.get("title", ""))
    desc = str(info.get("description", ""))
    text_tokens = set((title + " " + desc).lower().split())
    if query_tokens:
        overlap = len(query_tokens & text_tokens)
        score += 0.4 * min(overlap / len(query_tokens), 1.0)

    # Resolution: pixel count
    rendition = info.get("rendition") or {}
    w = rendition.get("width", 0) or 0
    h = rendition.get("height", 0) or 0
    if w > 0 and h > 0:
        area = w * h
        # 1080p = ~2M pixels, 4K = ~8M pixels
        # Normalize: 0 for tiny, 0.3 for 1080p+, extra for higher
        area_score = min(area / 2_000_000, 1.0)  # 1.0 = ~1080p or above
        score += 0.3 * area_score
    else:
        # Unknown resolution — neutral score (doesn't hurt, doesn't help)
        score += 0.1

    return score


def rank_videos(
    items: List[MaterialInfo],
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect,
) -> List[MaterialInfo]:
    """Rank candidate clips by relevance, duration, and resolution.

    Filters out:
      * Clips shorter than ``minimum_duration``
      * Clips with resolution below ``_MATERIAL_MIN_WIDTH`` x ``_MATERIAL_MIN_HEIGHT``
        (when resolution is known)

    Unlike ``_filter_materials_by_aspect`` (which rejects landscape clips for
    portrait output), this function ACCEPTS landscape clips — they will be
    reframed by the smart reframe pipeline. Clips with unknown resolution are
    retained (let the quality gate / reframing decide).

    Returns candidates sorted by descending score.
    """
    scored: list[tuple[float, MaterialInfo]] = []
    for item in items:
        info = item.source_info or {}
        dur = item.duration or 0

        # Filter: duration
        if dur < minimum_duration:
            continue

        # Filter: known-bad resolution (skip tiny clips)
        rendition = info.get("rendition") or {}
        w = rendition.get("width", 0) or 0
        h = rendition.get("height", 0) or 0
        if w > 0 and h > 0:
            if w < _MATERIAL_MIN_WIDTH or h < _MATERIAL_MIN_HEIGHT:
                continue

        score = _score_candidate(item, search_term, minimum_duration, video_aspect)
        scored.append((score, item))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored]


def _search_videos_with_cache(
    provider: str,
    search_videos: Callable[..., List[MaterialInfo]],
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect,
) -> List[MaterialInfo]:
    """
    统一处理三个在线素材源的 24 小时搜索缓存。

    缓存只包裹搜索 API，不改变后续视频下载与去重逻辑。远端返回空列表时不写
    缓存，因为现有 provider 接口使用空列表同时表示“没有结果”和“请求失败”；
    在两者尚未拆分为明确结果类型前，宁可下次重试，也不能把临时故障缓存一天。
    """
    cache_args = {
        "provider": provider,
        "search_term": search_term,
        "minimum_duration": minimum_duration,
        "video_aspect": video_aspect,
    }

    def load_cache_safely() -> List[MaterialInfo] | None:
        try:
            return material_cache.load_material_search_cache(**cache_args)
        except Exception as exc:
            # 缓存是可选优化，任何缓存实现异常都必须按未命中处理，不能阻断
            # Pexels、Pixabay 或 Coverr 的正常远端搜索。
            logger.warning(
                "material search cache read failed, continue with remote search: "
                f"provider={provider}, error={type(exc).__name__}, detail={exc}"
            )
            return None

    def load_matching_cache() -> tuple[List[MaterialInfo] | None, int]:
        cached_items = load_cache_safely()
        if cached_items is None:
            return None, 0

        filtered_cached_items = _filter_materials_by_aspect(
            cached_items,
            video_aspect,
        )
        ignored_count = len(cached_items) - len(filtered_cached_items)
        if ignored_count:
            # 旧版本缓存可能混入其它方向的素材。即使仍有少量可用条目，也要刷新
            # 完整候选集，否则在缓存有效期内会反复使用同一批少量视频。
            return None, ignored_count
        return filtered_cached_items, 0

    cached_items, ignored_count = load_matching_cache()
    if cached_items is not None:
        return cached_items
    if ignored_count:
        logger.info(
            "material search cache contains mismatched orientations, "
            f"refresh from provider: provider={provider}, term={search_term!r}, "
            f"ignored={ignored_count}"
        )

    cache_lock = material_cache.get_material_search_cache_lock(**cache_args)
    with cache_lock:
        # 等待相同搜索条件的线程完成后再次读取，避免多个 API 任务在首次缓存
        # 未命中时同时请求远端，降低第三方接口限流和风控触发概率。
        cached_items, _ = load_matching_cache()
        if cached_items is not None:
            return cached_items

        items = search_videos(
            search_term=search_term,
            minimum_duration=minimum_duration,
            video_aspect=video_aspect,
        )
        # Provider 正常会写入当前关键词，但测试替身、第三方扩展或旧实现可能
        # 遗漏或携带错误值。缓存读取会根据缓存键恢复该字段，因此远端结果也在
        # 同一入口校正，保证首次搜索与缓存命中的任务来源记录保持一致。
        for item in items:
            if isinstance(item.source_info, dict):
                item.source_info = dict(item.source_info)
                item.source_info["search_term"] = search_term
        if items:
            try:
                material_cache.save_material_search_cache(
                    **cache_args,
                    items=items,
                )
            except Exception as exc:
                logger.warning(
                    "material search cache write failed, use remote results: "
                    f"provider={provider}, error={type(exc).__name__}, detail={exc}"
                )
        return items


def download_videos(
    task_id: str,
    search_terms: List[str],
    source: str = "pexels",
    video_aspect: VideoAspect = VideoAspect.portrait,
    video_concat_mode: VideoConcatMode = VideoConcatMode.random,
    audio_duration: float = 0.0,
    max_clip_duration: int = 5,
    match_script_order: bool = False,
) -> List[str]:
    provider = "pexels"
    remote_search_videos = search_videos_pexels
    if source == "pixabay":
        provider = "pixabay"
        remote_search_videos = search_videos_pixabay
    elif source == "coverr":
        provider = "coverr"
        remote_search_videos = search_videos_coverr

    def search_videos(
        search_term: str,
        minimum_duration: int,
        video_aspect: VideoAspect,
    ) -> List[MaterialInfo]:
        return _search_videos_with_cache(
            provider=provider,
            search_videos=remote_search_videos,
            search_term=search_term,
            minimum_duration=minimum_duration,
            video_aspect=video_aspect,
        )

    material_directory = config.app.get("material_directory", "").strip()
    if material_directory == "task":
        material_directory = utils.task_dir(task_id)
    elif material_directory and not os.path.isdir(material_directory):
        material_directory = ""

    if source == "wavespeed":
        # AI 生成按条计费，不能沿用库存源"先为全部关键词取回候选、再挑选"
        # 的流程，否则会为用不到的片段付费。生成源改为逐段按需生成，凑够
        # 所需时长立即停止；也不参与 24 小时搜索缓存——产物 URL 是会过期
        # 的签名地址，且复用缓存会让不同任务反复得到同一段生成视频。
        return _download_videos_wavespeed_on_demand(
            task_id=task_id,
            search_terms=search_terms,
            video_aspect=video_aspect,
            audio_duration=audio_duration,
            max_clip_duration=max_clip_duration,
            material_directory=material_directory,
        )

    if match_script_order:
        return _download_videos_by_script_order(
            task_id=task_id,
            search_terms=search_terms,
            search_videos=search_videos,
            video_aspect=video_aspect,
            audio_duration=audio_duration,
            max_clip_duration=max_clip_duration,
            material_directory=material_directory,
        )

    valid_video_items = []
    valid_video_urls = []
    found_duration = 0.0
    for search_term in search_terms:
        video_items = search_videos(
            search_term=search_term,
            minimum_duration=max_clip_duration,
            video_aspect=video_aspect,
        )
        logger.info(f"found {len(video_items)} videos for '{search_term}'")

        for item in video_items:
            if item.url not in valid_video_urls:
                valid_video_items.append(item)
                valid_video_urls.append(item.url)
                found_duration += item.duration

    logger.info(
        f"found total videos: {len(valid_video_items)}, required duration: {audio_duration} seconds, found duration: {found_duration} seconds"
    )
    video_paths = []
    material_sources: list[dict[str, Any]] = []

    concat_mode_value = getattr(video_concat_mode, "value", video_concat_mode)
    if concat_mode_value == VideoConcatMode.random.value:
        random.shuffle(valid_video_items)

    total_duration = 0.0
    for item in valid_video_items:
        try:
            source_info = item.source_info if isinstance(item.source_info, dict) else {}
            logger.info(
                f"downloading {item.provider} video: "
                f"asset_id={source_info.get('asset_id') or 'unknown'}"
            )
            saved_video_path = save_video(
                video_url=item.url, save_dir=material_directory
            )
            if saved_video_path:
                logger.info(f"video saved: {saved_video_path}")
                video_paths.append(saved_video_path)
                try:
                    material_sources.append(
                        _material_source_record(item, saved_video_path)
                    )
                except Exception as source_error:
                    # 来源记录异常不能把已经成功下载的素材视为下载失败，更不能
                    # 阻断视频生成；保留供应商和异常类型用于后续定位。
                    logger.warning(
                        "failed to prepare material source record: "
                        f"provider={item.provider}, "
                        f"error={type(source_error).__name__}, detail={source_error}"
                    )
                seconds = min(max_clip_duration, item.duration)
                total_duration += seconds
                if total_duration > audio_duration:
                    logger.info(
                        f"total duration of downloaded videos: {total_duration} seconds, skip downloading more"
                    )
                    break
        except Exception as e:
            logger.error(
                "failed to download material video: "
                f"provider={item.provider}, error={type(e).__name__}, "
                f"detail={_redact_request_error(e, item.url)}"
            )
    logger.success(f"downloaded {len(video_paths)} videos")
    _persist_material_sources(task_id, material_sources)
    return video_paths


def _provider_and_searcher(source: str):
    """Resolve (provider_name, remote_search_fn) for a source, mirroring
    download_videos exactly so the legacy mapping is not duplicated."""
    provider = "pexels"
    remote_search_videos = search_videos_pexels
    if source == "pixabay":
        provider = "pixabay"
        remote_search_videos = search_videos_pixabay
    elif source == "coverr":
        provider = "coverr"
        remote_search_videos = search_videos_coverr
    elif source == "wavespeed":
        provider = "wavespeed"
        remote_search_videos = generate_videos_wavespeed
    elif source == "youtube":
        provider = "youtube"
        remote_search_videos = search_videos_youtube
    return provider, remote_search_videos


def _resolve_material_directory(task_id: str) -> str:
    """Same material_directory resolution as download_videos (kept local to
    avoid mutating the legacy function)."""
    material_directory = config.app.get("material_directory", "").strip()
    if material_directory == "task":
        material_directory = utils.task_dir(task_id)
    elif material_directory and not os.path.isdir(material_directory):
        material_directory = ""
    return material_directory


def _download_material_item(item: MaterialInfo, provider: str,
                              material_directory: str) -> str:
    """Download a single material item using the appropriate downloader.

    Tries HTTP-based ``save_video`` first (works for Pexels/Pixabay/Coverr).
    For YouTube items, also tries ``save_video_youtube`` (yt_dlp with cookie
    support) as a fallback when ``save_video`` fails (e.g. 403 bot detection).
    """
    saved = save_video(video_url=item.url, save_dir=material_directory)
    if saved:
        return saved
    if provider == "youtube" and yt_dlp is not None:
        logger.info(f"save_video failed for youtube, trying yt_dlp download: {item.url}")
        saved = save_video_youtube(video_url=item.url, save_dir=material_directory)
        if saved:
            return saved
    return ""


def download_videos_by_scene(
    task_id: str,
    video_scenes: list,
    source: str = "pixabay",
    video_aspect: VideoAspect = VideoAspect.portrait,
    max_clip_duration: int = 5,
    material_directory: str = "",
    sources: Optional[List[str]] = None,
) -> List[str]:
    """Scene-aware material path with multi-provider fallback + ranking + quality gate.

    For EACH scene, in exact scene order:
      scene.visual_query → provider candidates → ranking → download → quality gate

    The ``sources`` parameter is an ordered fallback list (e.g.
    ``["pexels", "pixabay", "youtube"]``).  For each scene the resolver tries
    providers left-to-right; the FIRST provider that returns a valid,
    downloadable, quality-gated clip wins that scene.

    Changes from the Phase 7B implementation:
      * Accepts ``sources`` list (backward-compatible: ``source`` still works).
      * Uses ``rank_videos()`` instead of ``usable[0]`` — scores by
        relevance, duration, and resolution; accepts landscape clips (reframed
        downstream).
      * Tries the next provider when one returns no usable candidates
        (fail-clean only when ALL providers are exhausted).
      * Quality-gates each downloaded clip via ffprobe + moviepy.

    Hard rules (enforced here):
      * ONE clip per scene (no pooling, no reuse).
      * If a scene has no usable material across ALL providers, the task FAILS
        CLEANLY with a message identifying scene index + visual_query.
      * No cross-scene substitution — ``used_asset_ids`` prevents reuse.

    Material sources are persisted with scene attribution (scene_index,
    visual_query, asset_id, provider) via ``_persist_material_sources``.

    Returns a scene-ordered list of downloaded clip file paths (1:1 with scenes).
    """
    # Backward compatibility: single ``source`` → single-element list
    if sources is None:
        sources = [source]

    if not material_directory:
        material_directory = _resolve_material_directory(task_id)

    video_paths: List[str] = []
    material_sources: list[dict] = []
    # "no clip reused" within a single render: two scenes may share a visual
    # query (e.g. the hook reuses the topic's first keyword), but they must
    # still receive DISTINCT material — each scene keeps its own selected clip
    # from its OWN query pool. This is never cross-scene substitution (a
    # different query's clip); it only skips an already-claimed asset from this
    # scene's own results and takes the next one.
    used_asset_ids: set[str] = set()

    for scene_index, scene in enumerate(video_scenes):
        visual_query = scene.get("visual_query") or ""
        scene_clip: Optional[str] = None
        scene_record: Optional[dict] = None
        selected_provider: Optional[str] = None

        for src in sources:
            provider, remote_search_videos = _provider_and_searcher(src)

            items = _search_videos_with_cache(
                provider=provider,
                search_videos=remote_search_videos,
                search_term=visual_query,
                minimum_duration=max_clip_duration,
                video_aspect=video_aspect,
            )

            # Rank candidates: filters by duration/resolution, scores by
            # relevance + resolution + duration.  Accepts all aspect ratios
            # (landscape clips are reframed downstream by BAGIAN C).
            ranked = rank_videos(
                items, visual_query, max_clip_duration, video_aspect
            )

            # Exclude assets already claimed by an earlier scene in THIS render.
            ranked = [
                m for m in ranked
                if (m.source_info or {}).get("asset_id") not in used_asset_ids
            ]

            if not ranked:
                logger.debug(
                    f"scene {scene_index}: provider={provider} returned no usable "
                    f"candidates after ranking for visual_query={visual_query!r}"
                )
                continue

            # Try candidates in ranked order (best first)
            for item in ranked:
                asset_id = (item.source_info or {}).get("asset_id")
                try:
                    saved_video_path = _download_material_item(
                        item, provider, material_directory
                    )
                except Exception as download_error:
                    logger.warning(
                        f"scene {scene_index}: download error for "
                        f"asset_id={asset_id}: {type(download_error).__name__}"
                    )
                    saved_video_path = ""

                if not saved_video_path:
                    logger.warning(
                        f"scene {scene_index}: download failed for "
                        f"asset_id={asset_id}, visual_query={visual_query!r}"
                    )
                    continue  # try next ranked candidate

                # Quality gate: validate the downloaded clip
                if not _validate_downloaded_clip(
                    saved_video_path, min_duration=max_clip_duration,
                    video_aspect=video_aspect
                ):
                    logger.warning(
                        f"scene {scene_index}: quality gate rejected clip "
                        f"asset_id={asset_id}, visual_query={visual_query!r}"
                    )
                    # Clean up the rejected file to prevent large unusable
                    # downloads from permanently consuming disk space.
                    # The file failed the quality gate for all consumers;
                    # deleting it is safe and idempotent.
                    try:
                        if saved_video_path and os.path.isfile(saved_video_path):
                            os.remove(saved_video_path)
                            logger.info(
                                f"cleaned up quality-rejected clip: "
                                f"{os.path.basename(saved_video_path)}"
                            )
                    except OSError as cleanup_error:
                        logger.warning(
                            f"failed to remove quality-rejected clip "
                            f"{saved_video_path}: {cleanup_error}"
                        )
                    continue  # try next ranked candidate

                # Success — this clip is the winner for this scene
                scene_clip = saved_video_path
                selected_provider = provider
                used_asset_ids.add(asset_id)

                try:
                    record = _material_source_record(item, saved_video_path)
                except Exception as source_error:
                    logger.warning(
                        f"failed to build material source record for scene "
                        f"{scene_index}: {type(source_error).__name__}, "
                        f"detail={source_error}"
                    )
                    record = {
                        "provider": getattr(item, "provider", provider) or provider,
                        "local_file": Path(saved_video_path).name,
                        "duration": int(getattr(item, "duration", 0) or 0),
                    }

                # Scene attribution for the auditable scene->asset->timeline mapping.
                record["scene_index"] = scene_index
                record["visual_query"] = visual_query
                record["narration"] = scene.get("narration", "")
                if item.source_info and isinstance(
                    item.source_info.get("asset_id"), str
                ):
                    record.setdefault("asset_id", item.source_info["asset_id"])

                scene_record = record
                break  # stop trying candidates for this scene

            if scene_clip:
                break  # stop trying providers for this scene

        if not scene_clip:
            logger.error(
                f"scene {scene_index} failed across all providers: "
                f"visual_query={visual_query!r}, sources={sources}"
            )
            raise RuntimeError(
                f"scene {scene_index} has no usable material for "
                f"visual_query {visual_query!r} "
                f"(sources={sources}); all providers exhausted, "
                f"skipping another scene's clip is not allowed"
            )

        video_paths.append(scene_clip)
        material_sources.append(scene_record)
        logger.info(
            f"scene {scene_index} material selected: "
            f"visual_query={visual_query!r}, "
            f"asset_id={scene_record.get('asset_id')}, "
            f"provider={selected_provider}"
        )

    _persist_material_sources(task_id, material_sources)
    return video_paths


def _download_videos_wavespeed_on_demand(

    *,
    task_id: str,
    search_terms: List[str],
    video_aspect: VideoAspect,
    audio_duration: float,
    max_clip_duration: int,
    material_directory: str,
) -> List[str]:
    """
    按脚本片段顺序逐段生成 WaveSpeed 素材，凑够所需总时长立即停止。

    每个关键词天然对应一个脚本片段，生成即付费：先全量生成再挑选会为
    用不到的片段付费。这里每生成一段就立刻下载并累计有效时长（与库存
    流程一致，按片段时长封顶），累计超过所需配音时长后不再触发新的生成
    请求。单段失败按现有素材源约定跳过并继续下一段。
    """
    video_paths: List[str] = []
    material_sources: list[dict[str, Any]] = []
    total_duration = 0.0
    for search_term in search_terms:
        try:
            video_items = generate_videos_wavespeed(
                search_term=search_term,
                minimum_duration=max_clip_duration,
                video_aspect=video_aspect,
            )
        except WaveSpeedUnconfirmedTaskError as e:
            # 已提交的付费任务状态不明：远端可能仍在运行或已经完成并计费。
            # 继续为后续关键词下单会造成重复生成和重复扣费，因此就地停止，
            # 并把 prediction id 留在日志里供人工在控制台找回产物。
            logger.error(
                "stop submitting new wavespeed tasks, the last submitted task "
                f"is unconfirmed: prediction_id={e.prediction_id or 'unknown'}, "
                f"detail={e}"
            )
            break
        for item in video_items:
            saved_video_path = _save_wavespeed_video_with_retry(
                item.url, material_directory
            )
            if not saved_video_path:
                continue
            logger.info(f"video saved: {saved_video_path}")
            video_paths.append(saved_video_path)
            try:
                material_sources.append(_material_source_record(item, saved_video_path))
            except Exception as source_error:
                # 与库存源一致：来源记录异常不能把已经付费生成并成功下载的
                # 素材当作失败，更不能阻断视频生成。
                logger.warning(
                    "failed to prepare material source record: "
                    f"provider={item.provider}, "
                    f"error={type(source_error).__name__}, detail={source_error}"
                )
            total_duration += min(max_clip_duration, item.duration)
            # 用 >= 判断:累计时长恰好等于所需时长时已经够用,再生成会
            # 多付一次费用。内外两处判断必须保持同一语义。
            if total_duration >= audio_duration:
                break
        if total_duration >= audio_duration:
            logger.info(
                "generated materials cover the required duration, stop "
                f"generating more clips: generated={total_duration:.1f}s, "
                f"required={audio_duration:.1f}s"
            )
            break
    logger.success(f"generated and downloaded {len(video_paths)} videos")
    _persist_material_sources(task_id, material_sources)
    return video_paths


def _download_videos_by_script_order(
    task_id: str,
    search_terms: List[str],
    search_videos,
    video_aspect: VideoAspect,
    audio_duration: float,
    max_clip_duration: int,
    material_directory: str,
) -> List[str]:
    """
    按脚本文案顺序下载素材。

    默认下载逻辑会把所有关键词的候选素材合并成一个大列表；如果第一个
    关键词返回很多结果，最终下载时可能一直消耗这个关键词的素材，后续
    脚本主题就排不上时间线。这里按关键词分组后轮询下载：
    第 1 轮取每个关键词的第 1 个候选，第 2 轮取每个关键词的第 2 个候选。
    这样在不重写视频合成引擎的前提下，尽量保证素材顺序贴近文案顺序。
    """
    logger.info("downloading videos with script-order material matching")
    candidate_groups = []
    valid_video_urls = set()
    found_duration = 0.0

    for search_term in search_terms:
        video_items = search_videos(
            search_term=search_term,
            minimum_duration=max_clip_duration,
            video_aspect=video_aspect,
        )
        logger.info(f"found {len(video_items)} videos for '{search_term}'")

        term_items = []
        for item in video_items:
            if item.url in valid_video_urls:
                continue
            term_items.append(item)
            valid_video_urls.add(item.url)
            found_duration += item.duration

        if term_items:
            candidate_groups.append((search_term, term_items))

    logger.info(
        f"found total ordered video candidates: {sum(len(items) for _, items in candidate_groups)}, "
        f"required duration: {audio_duration} seconds, found duration: {found_duration} seconds"
    )

    video_paths = []
    material_sources: list[dict[str, Any]] = []
    total_duration = 0.0
    candidate_index = 0
    while candidate_groups and total_duration <= audio_duration:
        has_candidate = False
        for search_term, term_items in candidate_groups:
            if candidate_index >= len(term_items):
                continue

            has_candidate = True
            item = term_items[candidate_index]
            try:
                source_info = (
                    item.source_info if isinstance(item.source_info, dict) else {}
                )
                logger.info(
                    f"downloading ordered {item.provider} video for {search_term!r}: "
                    f"asset_id={source_info.get('asset_id') or 'unknown'}"
                )
                saved_video_path = save_video(
                    video_url=item.url, save_dir=material_directory
                )
                if saved_video_path:
                    logger.info(f"video saved: {saved_video_path}")
                    video_paths.append(saved_video_path)
                    try:
                        material_sources.append(
                            _material_source_record(item, saved_video_path)
                        )
                    except Exception as source_error:
                        logger.warning(
                            "failed to prepare ordered material source record: "
                            f"provider={item.provider}, "
                            f"error={type(source_error).__name__}, "
                            f"detail={source_error}"
                        )
                    total_duration += min(max_clip_duration, item.duration)
                    if total_duration > audio_duration:
                        logger.info(
                            f"total duration of downloaded videos: {total_duration} seconds, skip downloading more"
                        )
                        break
            except Exception as e:
                logger.error(
                    "failed to download ordered material video: "
                    f"provider={item.provider}, error={type(e).__name__}, "
                    f"detail={_redact_request_error(e, item.url)}"
                )

        if not has_candidate:
            break
        candidate_index += 1

    logger.success(f"downloaded {len(video_paths)} ordered videos")
    _persist_material_sources(task_id, material_sources)
    return video_paths


# ─── Safe orphan cache_videos sweeper ───────────────────────────────────────

# Default TTL for cached raw media in cache_videos/.  Files older than this
# that are not referenced by an active (processing) task are eligible for
# deletion.  30 days is conservative: long enough for any legitimate reuse
# within a month, short enough to bound disk growth from stale downloads.
_CACHE_VIDEOS_TTL_DAYS = 30

# Patterns recognized for cleanup in cache_videos/.  Anything outside these
# patterns is ALWAYS preserved (fail-closed for unknown filenames).
_CACHE_VIDEOS_FILE_PATTERNS = [
    re.compile(r"^vid-([0-9a-f]{32})\.mp4$"),
    re.compile(r"^vid-([0-9a-f]{32})\.mp4\.part$"),
    re.compile(r"^vid-([0-9a-f]{32})\.mp4\.ytdl$"),
    re.compile(r"^vid-[0-9a-f]{32}\.mp4\.Frag\d+$"),
]

# File names that must NEVER be deleted by the sweeper, even if they appear
# in cache_videos/.  These are per-task production artifacts.
_PROTECTED_FILENAMES = {
    "final-1.mp4", "combined-1.mp4", "audio.mp3",
    "subtitle.srt", "script.json", "scene_timing.json",
}

# Active task states — only files referenced by tasks in these states are kept
_ACTIVE_TASK_STATES = {const.TASK_STATE_PROCESSING}


def _get_active_cache_references() -> set[str]:
    """Collect the set of cache_videos filenames currently referenced by
    active (processing) tasks.

    Returns an empty set if task state cannot be reliably inspected
    (fail-closed: empty set means 'no known references' but the caller
    must still check age before deleting).
    """
    references: set[str] = set()
    try:
        # Page through all tasks.  Use a large page size to minimize round-trips.
        tasks, total = sm.state.get_all_tasks(page=1, page_size=1000)
    except Exception as e:
        # If we cannot read task state at all (e.g. Redis unavailable, or
        # in-memory state lost on restart), return empty.  The caller will
        # keep all files because it cannot confirm they are unreferenced.
        logger.debug(f"orphan sweeper: cannot read task state ({e}); "
                     f"treating all files as potentially active")
        return references

    for task in tasks:
        state_val = task.get("state")
        try:
            state_val = int(state_val)
        except (TypeError, ValueError):
            continue
        if state_val not in _ACTIVE_TASK_STATES:
            continue

        # The task stores ``materials`` as a list of file paths (full paths
        # to downloaded clips).  Extract the basename for cache lookup.
        materials = task.get("materials")
        if not isinstance(materials, list):
            continue
        for mat_path in materials:
            if isinstance(mat_path, str) and mat_path:
                references.add(os.path.basename(mat_path))

    return references


def cleanup_orphan_cache_videos(
    cache_dir: str | None = None,
    ttl_days: int = _CACHE_VIDEOS_TTL_DAYS,
) -> int:
    """Remove stale, unreferenced files from ``cache_videos/``.

    Recognizes only expected temporary/cache patterns:
    ``vid-{32-hex}.mp4``, ``.part``, ``.ytdl``, ``.Frag*``.
    Production artifacts (``final-*``, ``combined-*``, ``audio.mp3``, etc.)
    and unknown files are never deleted.

    For each candidate:
      1. Verify it is a regular file.
      2. Verify filename matches an allowed pattern.
      3. Check age — keep if younger than ``ttl_days``.
      4. If older than TTL, check if referenced by an active task.
      5. If actively referenced: KEEP.
      6. If not actively referenced: DELETE.
      7. Unknown/unrecognized files: KEEP (fail-closed).
      8. Any inspection error: KEEP.
      9. Any deletion error: log warning, continue.

    Returns the number of files deleted.
    """
    if cache_dir is None:
        cache_dir = utils.storage_dir("cache_videos")

    if not os.path.isdir(cache_dir):
        return 0

    # Collect active references for the fail-closed KEEP rule.
    active_refs = _get_active_cache_references()

    ttl_seconds = ttl_days * 86400
    now = time.time()
    deleted_count = 0

    try:
        entries = os.listdir(cache_dir)
    except OSError as e:
        logger.warning(
            f"orphan sweeper: cannot list cache_videos ({e}); skipping"
        )
        return 0

    for filename in entries:
        # Absolute safety: never touch protected filenames
        if filename in _PROTECTED_FILENAMES:
            continue

        filepath = os.path.join(cache_dir, filename)

        # 1. Verify it is a regular file
        try:
            if not os.path.isfile(filepath):
                continue
        except OSError:
            continue

        # 2. Verify filename matches an allowed pattern
        if not any(p.match(filename) for p in _CACHE_VIDEOS_FILE_PATTERNS):
            # 8. Unknown/unrecognized files: KEEP
            continue

        # 3. Check age
        try:
            mtime = os.path.getmtime(filepath)
        except OSError as e:
            # 9. Any inspection error: KEEP
            logger.debug(
                f"orphan sweeper: cannot stat {filename} ({e}); keeping"
            )
            continue

        age_seconds = now - mtime
        if age_seconds < ttl_seconds:
            # 4. Younger than TTL: KEEP
            continue

        # 5. Check active references (fail-closed)
        if filename in active_refs:
            continue

        # 6. DELETE
        try:
            os.remove(filepath)
            deleted_count += 1
            logger.info(f"orphan sweeper: deleted stale cache file {filename}")
        except OSError as e:
            # 10. Any deletion error: log warning, continue
            logger.warning(
                f"orphan sweeper: failed to delete {filepath}: {e}"
            )

    return deleted_count


def run_startup_cleanup() -> None:
    """Run all safe startup-time cleanup tasks.

    Called from the ASGI lifespan on application startup.
    Currently cleans orphan cache_videos/ files.
    """
    try:
        deleted = cleanup_orphan_cache_videos()
        if deleted > 0:
            logger.info(f"startup cleanup: deleted {deleted} orphan cache files")
    except Exception as e:
        logger.warning(f"startup cleanup: sweeper error (safely ignored): {e}")


if __name__ == "__main__":
    download_videos(
        "test123", ["Money Exchange Medium"], audio_duration=100, source="pixabay"
    )
