import os
from datetime import date
from pathlib import Path
import json
from typing import Any


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_csv(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _env_json_list(name: str, default: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return default
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    return default


def _unique_nonempty(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return tuple(ordered)


def _find_workspace_dir(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "shared" / "config.json").exists():
            return candidate
    return start


def _default_media_crawler_dir() -> str:
    candidates = (
        WORKSPACE_DIR.parent / "MediaCrawler",
        WORKSPACE_DIR / "MediaCrawler",
    )
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return ""


MODULE_DIR = Path(__file__).resolve().parent
BASE_DIR = MODULE_DIR.parent
WORKSPACE_DIR = _find_workspace_dir(BASE_DIR)
CONFIG_DIR = BASE_DIR / "config"
USER_HOME = Path.home()

DEFAULT_CASEY_PROFILE: dict[str, Any] = {
    "account_id": "casey",
    "display_name": "添爸",
    "positioning": {
        "one_liner": "添爸，用医疗科技投资人的视角，讲医保、用药安全和医疗消费避坑，讲给关心父母健康的家庭决策者。",
        "identity": "添爸（10年+医疗科技投资人视角）",
        "topic": "医保、用药安全、医疗消费避坑、医疗政策与产业翻译",
        "audience": "关心父母健康的子女、家庭健康决策者，以及会在家族群传播健康信息的中老年群体",
    },
    "capability_boundary": {
        "can_discuss": [
            "医保、药价、报销与进院难",
            "用药安全、家庭药箱与器械避坑",
            "医疗政策、监管、供应链与质量标准",
            "健康消费骗局、私域营销和抗衰概念避坑",
        ],
        "never_touch": [
            "个体化诊断结论",
            "具体处方、剂量或替代医生的用药建议",
            "承诺疗效、推荐具体品牌或型号",
            "未核实数据、歪曲政策、超出能力圈的投资理财建议",
        ],
    },
    "dual_audience_model": {
        "decision_layer": {
            "label": "李姐",
            "who": "35-45 岁家庭健康决策者，关心药费、报销、是否值得收藏转发。",
            "drives": "决定选题方向、信息密度和收藏价值。",
            "expected_action": "点开/收藏",
        },
        "spread_layer": {
            "label": "张阿姨",
            "who": "55+ 中老年家庭成员，关心药费和健康风险，爱转家族群。",
            "drives": "决定标题语言、表达方式和家族群传播性。",
            "expected_action": "转发到家族群",
        },
    },
    "content_mix": {
        "lines": [
            {
                "key": "public_issue",
                "name": "医疗公共议题",
                "weight": 0.5,
                "description": "医保、集采、药价、监管、进院难等公共议题。",
            },
            {
                "key": "family_anxiety",
                "name": "家庭健康焦虑",
                "weight": 0.3,
                "description": "儿童用药、老人风险、家庭药箱与常见误区。",
            },
            {
                "key": "consumer_scam",
                "name": "健康消费避坑",
                "weight": 0.2,
                "description": "抗衰、医美、私域保健品和概念营销骗局。",
            },
        ],
        "roles": [
            {
                "key": "spread",
                "name": "传播款",
                "weight": 0.4,
                "description": "适合引发转发、评论和外圈传播。",
            },
            {
                "key": "save",
                "name": "收藏款",
                "weight": 0.4,
                "description": "适合收藏、反复查看和家庭内部分享。",
            },
            {
                "key": "followup",
                "name": "追问款",
                "weight": 0.2,
                "description": "承接已有热点或系列选题的追问、补充和答疑。",
            },
        ],
    },
    "creator_notes": "优先用政策、定价、供应链、质量标准和家庭消费决策的视角解释问题。",
}


def _deep_copy_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = _deep_copy_json(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_json_dict(path: str | os.PathLike[str]) -> dict[str, Any] | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _extract_weight_map(entries: Any, fallback: dict[str, float]) -> dict[str, float]:
    if not isinstance(entries, list):
        return dict(fallback)

    extracted: dict[str, float] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("key") or "").strip()
        if key not in fallback:
            continue
        try:
            weight = float(entry.get("weight"))
        except (TypeError, ValueError):
            continue
        if weight < 0:
            continue
        extracted[key] = round(weight, 3)

    if not extracted:
        return dict(fallback)

    merged = dict(fallback)
    merged.update(extracted)
    return merged


CASEY_PROFILE_PATH = os.getenv("CASEY_PROFILE_PATH", str(CONFIG_DIR / "casey_profile.json"))
HOTMIC_ROOT_PATH = os.getenv("HOTMIC_ROOT_PATH", str(WORKSPACE_DIR))
HOTMIC_SHARED_CONFIG_PATH = os.getenv(
    "HOTMIC_SHARED_CONFIG_PATH",
    str(Path(HOTMIC_ROOT_PATH) / "shared" / "config.json"),
)
HOTMIC_STYLE_DB_PATH = os.getenv(
    "HOTMIC_STYLE_DB_PATH",
    str(Path(HOTMIC_ROOT_PATH) / "shared" / "style_db.json"),
)
HOTMIC_REVIEW_ENGINE_DIR = os.getenv(
    "HOTMIC_REVIEW_ENGINE_DIR",
    str(Path(HOTMIC_ROOT_PATH) / "hotmic-review-engine"),
)
HOTMIC_SCRIPT_CREATOR_DIR = os.getenv(
    "HOTMIC_SCRIPT_CREATOR_DIR",
    str(Path(HOTMIC_ROOT_PATH) / "hotmic-script-creator"),
)
HOTMIC_STYLE_CONFIDENCE_THRESHOLD = float(os.getenv("HOTMIC_STYLE_CONFIDENCE_THRESHOLD", "0.6"))


def load_casey_profile(profile_path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    loaded = _load_json_dict(profile_path or CASEY_PROFILE_PATH)
    if not loaded:
        return _deep_copy_json(DEFAULT_CASEY_PROFILE)
    return _merge_dict(DEFAULT_CASEY_PROFILE, loaded)


def load_casey_target_mix(profile_path: str | os.PathLike[str] | None = None) -> dict[str, float]:
    profile = load_casey_profile(profile_path)
    fallback = {"public_issue": 0.5, "family_anxiety": 0.3, "consumer_scam": 0.2}
    lines = ((profile.get("content_mix") or {}).get("lines") or [])
    return _extract_weight_map(lines, fallback)


def load_casey_role_mix(profile_path: str | os.PathLike[str] | None = None) -> dict[str, float]:
    profile = load_casey_profile(profile_path)
    fallback = {"spread": 0.4, "save": 0.4, "followup": 0.2}
    roles = ((profile.get("content_mix") or {}).get("roles") or [])
    return _extract_weight_map(roles, fallback)


# Runtime
APP_VERSION = "0.1.0"
MOCK_MODE = _env_bool("MOCK_MODE", False)

# AI API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_FLASH_MODEL = os.getenv("GEMINI_FLASH_MODEL", "gemini-flash-latest")
QWEN_API_KEY = os.getenv("QWEN_API_KEY")
QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen-plus")
PREFILTER_ENABLED = _env_bool("PREFILTER_ENABLED", False)
PREFILTER_MODEL = os.getenv("PREFILTER_MODEL", QWEN_MODEL)
PREFILTER_THRESHOLD = float(os.getenv("PREFILTER_THRESHOLD", "0.3"))
ANALYZE_MODEL = os.getenv("ANALYZE_MODEL", QWEN_MODEL)
ANALYZE_API_KEY = os.getenv("ANALYZE_API_KEY", "")
ANALYZE_BASE_URL = os.getenv("ANALYZE_BASE_URL", QWEN_BASE_URL)
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
USD_PER_CNY = float(os.getenv("USD_PER_CNY", "0.145"))

# Feishu (reserved for later stages)
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "cli_a90dcebdebb8dcca")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET")
BITABLE_APP_TOKEN = os.getenv("BITABLE_APP_TOKEN")
TOPICS_TABLE_ID = os.getenv("TOPICS_TABLE_ID")
FRAMES_TABLE_ID = os.getenv("FRAMES_TABLE_ID")
FEISHU_BASE_URL = os.getenv("FEISHU_BASE_URL", "https://open.feishu.cn")

# Data collection
BAIDU_API_KEY = os.getenv("BAIDU_API_KEY")
BRAVE_SEARCH_API_KEY = os.getenv("BRAVE_SEARCH_API_KEY")
BRAVE_SEARCH_API_KEY_2 = os.getenv("BRAVE_SEARCH_API_KEY_2")
BRAVE_SEARCH_API_KEYS = _unique_nonempty(
    [BRAVE_SEARCH_API_KEY or "", BRAVE_SEARCH_API_KEY_2 or "", *_env_csv("BRAVE_SEARCH_API_KEYS")]
)
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
TAVILY_ENABLED = _env_bool("TAVILY_ENABLED", False)
RSS_WECHAT = os.getenv("RSS_WECHAT", "")
RAW_POOL_LIMIT = int(os.getenv("RAW_POOL_LIMIT", "80"))
RSS_ITEM_LIMIT = int(os.getenv("RSS_ITEM_LIMIT", "25"))
BRAVE_QUERY_LIMIT = int(os.getenv("BRAVE_QUERY_LIMIT", "10"))
BRAVE_RESULT_COUNT = int(os.getenv("BRAVE_RESULT_COUNT", "5"))
TAVILY_QUERY_LIMIT = int(os.getenv("TAVILY_QUERY_LIMIT", "3"))
TAVILY_RESULT_COUNT = int(os.getenv("TAVILY_RESULT_COUNT", "5"))
BAIDU_RESULT_COUNT = int(os.getenv("BAIDU_RESULT_COUNT", "8"))
HTML_SOURCE_ITEM_LIMIT = int(os.getenv("HTML_SOURCE_ITEM_LIMIT", "8"))
WEWE_BASE_URL = os.getenv(
    "WEWE_BASE_URL",
    RSS_WECHAT.split("/feeds/", 1)[0] if "/feeds/" in RSS_WECHAT else "",
)
WEWE_AUTH_CODE = os.getenv("WEWE_AUTH_CODE")
WEWE_PLATFORM_URL = os.getenv("WEWE_PLATFORM_URL", "")
MEDIA_CRAWLER_DIR = os.getenv("MEDIA_CRAWLER_DIR", _default_media_crawler_dir())
MEDIA_CRAWLER_ENABLED = _env_bool(
    "MEDIA_CRAWLER_ENABLED",
    bool(MEDIA_CRAWLER_DIR) and Path(MEDIA_CRAWLER_DIR).exists(),
)
MEDIA_CRAWLER_REFRESH_TIMEOUT = int(os.getenv("MEDIA_CRAWLER_REFRESH_TIMEOUT", "75"))
MEDIA_CRAWLER_ITEM_LIMIT = int(os.getenv("MEDIA_CRAWLER_ITEM_LIMIT", "12"))
MEDIA_CRAWLER_MAX_AGE_HOURS = int(os.getenv("MEDIA_CRAWLER_MAX_AGE_HOURS", "6"))
MEDIA_CRAWLER_DOUYIN_KEYWORDS = os.getenv(
    "MEDIA_CRAWLER_DOUYIN_KEYWORDS",
    "医保 用药安全 医疗器械 体外诊断 IVD 生物科技 biotech BTIT 创新药",
)
MEDIA_CRAWLER_XHS_KEYWORDS = os.getenv(
    "MEDIA_CRAWLER_XHS_KEYWORDS",
    "医保 创新药 医疗器械 体外诊断 生物科技 biotech BTIT",
)
SEARCH_PICKS_PER_LAYER = int(os.getenv("SEARCH_PICKS_PER_LAYER", "2"))
ANALYZER_BATCH_SIZE = int(os.getenv("ANALYZER_BATCH_SIZE", "8"))
ANALYZER_BATCH_CONCURRENCY = int(os.getenv("ANALYZER_BATCH_CONCURRENCY", "3"))
QWEN_ANALYZE_TIMEOUT = float(os.getenv("QWEN_ANALYZE_TIMEOUT", "45"))
ANALYSIS_CACHE_ENABLED = _env_bool("ANALYSIS_CACHE_ENABLED", False)
ANALYSIS_CACHE_LOOKBACK_DAYS = int(os.getenv("ANALYSIS_CACHE_LOOKBACK_DAYS", "7"))
PUBLIC_ISSUE_KEYWORDS = [
    "原研药 仿制药 差别",
    "医保 报销 变化",
    "集采 降价 最新",
    "药价 调整 患者",
    "药品安全 通报",
    "医疗政策 新规",
    "创新药 进医保",
    "高价药 支付 压力",
    "药进医保 医院 开不出来",
    "创新药 进院难 患者 用不上",
    "医保药 医院 开不出 原因",
]
FAMILY_ANXIETY_KEYWORDS = [
    "保健品 老人 被骗 最新",
    "体检报告 看不懂 白花钱",
    "药 副作用 不敢吃",
    "医院 过度检查",
    "儿童 用药 风险",
    "家庭 药箱 误区",
    "老人 健康 风险",
    "家庭 医疗 误区",
    "私域营销 老人 健康讲座",
    "老人 养老金 健康讲座 卖货",
    "褪黑素 儿童 睡眠 风险",
]
CONSUMER_SCAM_KEYWORDS = [
    "基因检测 交智商税",
    "外泌体 美容 骗局 真相",
    "NAD+ 抗衰 骗局",
    "司美格鲁肽 灰市 风险",
    "网红 健康 产品 避坑",
    "医美 点滴 风险",
    "保健品 营销 夸大",
    "抗衰 医美 争议",
    "315 外泌体 点名",
    "315 私域营销 专家之谜",
    "315 增高 营销 套路",
]
PRIORITY_FALLBACK_KEYWORDS = {
    "public_issue": [
        "药进医保 医院 开不出来",
        "创新药 进院难 患者 用不上",
    ],
    "family_anxiety": [
        "私域营销 老人 健康讲座",
        "老人 养老金 健康讲座 卖货",
    ],
    "consumer_scam": [
        "315 外泌体 点名",
        "315 私域营销 专家之谜",
    ],
}
SEARCH_KEYWORDS = {
    "public_issue": PUBLIC_ISSUE_KEYWORDS,
    "family_anxiety": FAMILY_ANXIETY_KEYWORDS,
    "consumer_scam": CONSUMER_SCAM_KEYWORDS,
}
RSS_DISCOVERY_BASKET_SOURCES = [
    {
        "url": os.getenv("RSS_BASKET_STATS_RELEASE", "https://www.stats.gov.cn/sj/zxfb/rss.xml"),
        "source": "rss_stats_release",
    },
    {
        "url": os.getenv("RSS_BASKET_STATS_INTERPRETATION", "https://www.stats.gov.cn/sj/sjjd/rss.xml"),
        "source": "rss_stats_interpretation",
    },
    {
        "url": os.getenv(
            "RSS_BASKET_FDA_MEDWATCH",
            "https://www.fda.gov/AboutFDA/ContactFDA/StayInformed/RSSFeeds/MedWatch/rss.xml",
        ),
        "source": "rss_fda_medwatch",
    },
    {
        "url": os.getenv("RSS_BACKUP_STAT", "https://www.statnews.com/feed/"),
        "source": "rss_stat_backup",
    },
    {
        "url": os.getenv(
            "RSS_BACKUP_SCIENCEDAILY",
            "https://www.sciencedaily.com/rss/health_medicine.xml",
        ),
        "source": "rss_sciencedaily_health",
    },
    {
        "url": os.getenv(
            "RSS_BACKUP_NYT_HEALTH",
            "https://rss.nytimes.com/services/xml/rss/nyt/Health.xml",
        ),
        "source": "rss_nyt_health",
    },
    {
        "url": os.getenv("RSS_36KR", "https://36kr.com/feed"),
        "source": "rss_36kr",
    },
    {
        "url": os.getenv("RSS_HUXIU", "https://rss.huxiu.com/"),
        "source": "rss_huxiu",
    },
    {
        "url": os.getenv("RSS_IFANR", "https://www.ifanr.com/feed"),
        "source": "rss_ifanr",
    },
    {
        "url": os.getenv("RSS_GEEKPARK", "http://feeds.geekpark.net/"),
        "source": "rss_geekpark",
    },
    {
        "url": os.getenv("RSS_DXY", "https://www.dxy.cn/bbs/rss/2.0/all.xml"),
        "source": "rss_dxy",
    },
]
SITE_SEARCH_TARGETS = _env_json_list(
    "SITE_SEARCH_TARGETS",
    [
        {"site": "mp.weixin.qq.com", "keyword": "赛柏蓝", "source": "wx_saibolan"},
        {"site": "mp.weixin.qq.com", "keyword": "瞪羚社", "source": "wx_denglings"},
        {"site": "mp.weixin.qq.com", "keyword": "学术经纬", "source": "wx_xsjw"},
        {"site": "mp.weixin.qq.com", "keyword": "医业观察", "source": "wx_yygc"},
        {"site": "mp.weixin.qq.com", "keyword": "智药局", "source": "wx_zhiyaoju"},
        {"site": "pedaily.cn", "keyword": "医疗 OR 医药 OR 器械", "source": "pedaily_med"},
        {"site": "pharmcube.com", "keyword": "", "source": "pharmcube"},
    ],
)
COMPETITOR_ACCOUNTS = _env_json_list("COMPETITOR_ACCOUNTS", [])

# Proxy
HTTP_PROXY = os.getenv("HTTP_PROXY") or None
HTTPS_PROXY = os.getenv("HTTPS_PROXY") or None
NO_PROXY = os.getenv("NO_PROXY") or None
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
DOUYIN_COOKIE_PATH = os.getenv(
    "DOUYIN_COOKIE_PATH",
    str(USER_HOME / ".openclaw" / "hotmic-ai" / "superdirector" / ".douyin_cookie"),
)
SUPERDIRECTOR_SERVICE_PATH = os.getenv(
    "SUPERDIRECTOR_SERVICE_PATH",
    str(USER_HOME / ".config" / "systemd" / "user" / "superdirector.service"),
)

# Database
SQLITE_PATH = os.getenv("SQLITE_PATH", str(BASE_DIR / "data" / "superdirector.db"))
TOPIC_CLUSTERS_PATH = os.getenv(
    "TOPIC_CLUSTERS_PATH",
    str(CONFIG_DIR / "topic_clusters.json"),
)
EDITORIAL_HINTS_PATH = os.getenv(
    "EDITORIAL_HINTS_PATH",
    str(CONFIG_DIR / "editorial_hints.json"),
)

# Pipeline
DAILY_RUN_HOUR = int(os.getenv("DAILY_RUN_HOUR", "8"))
DAILY_RUN_MINUTE = int(os.getenv("DAILY_RUN_MINUTE", "0"))
TOPICS_PER_RUN = int(os.getenv("TOPICS_PER_RUN", "5"))
TOP_N = int(os.getenv("TOP_N", "5"))
FRAME_TOP_N = int(os.getenv("FRAME_TOP_N", "5"))
EVERGREEN_POOL_PATH = os.getenv(
    "EVERGREEN_POOL_PATH",
    str(BASE_DIR / "data" / "evergreen_topics.json"),
)
EVERGREEN_DAILY_COUNT = int(os.getenv("EVERGREEN_DAILY_COUNT", "2"))
PIPELINE_STEP_TIMEOUT_SECONDS = int(os.getenv("PIPELINE_STEP_TIMEOUT_SECONDS", "600"))
PIPELINE_RUN_STALE_SECONDS = int(os.getenv("PIPELINE_RUN_STALE_SECONDS", "900"))
SCHEDULER_ENABLED = _env_bool("SCHEDULER_ENABLED", False)
SCHEDULER_CRON_HOUR = int(os.getenv("SCHEDULER_CRON_HOUR", "8"))
SCHEDULER_CRON_MINUTE = int(os.getenv("SCHEDULER_CRON_MINUTE", "0"))
EDITORIAL_PHASE = int(os.getenv("EDITORIAL_PHASE", "1"))
EDITORIAL_RECENT_WINDOW_DAYS = int(os.getenv("EDITORIAL_RECENT_WINDOW_DAYS", "7"))
EDITORIAL_PERFORMANCE_LOOKBACK_DAYS = int(os.getenv("EDITORIAL_PERFORMANCE_LOOKBACK_DAYS", "30"))
EDITORIAL_ROLE_BASELINE_THRESHOLD = float(os.getenv("EDITORIAL_ROLE_BASELINE_THRESHOLD", "4.2"))
EDITORIAL_TARGET_MIX_DEFAULT = load_casey_target_mix()
EDITORIAL_TARGET_ROLE_MIX_DEFAULT = load_casey_role_mix()
EDITORIAL_FATIGUE_WINDOW_DAYS = int(os.getenv("EDITORIAL_FATIGUE_WINDOW_DAYS", "7"))
EDITORIAL_FATIGUE_PENALTY_STEP = float(os.getenv("EDITORIAL_FATIGUE_PENALTY_STEP", "0.18"))
EDITORIAL_SOURCE_CONCENTRATION_PENALTY = float(os.getenv("EDITORIAL_SOURCE_CONCENTRATION_PENALTY", "0.12"))
EDITORIAL_HIGH_RISK_PENALTY = float(os.getenv("EDITORIAL_HIGH_RISK_PENALTY", "99"))
EDITORIAL_MEDIUM_RISK_PENALTY = float(os.getenv("EDITORIAL_MEDIUM_RISK_PENALTY", "0.35"))
EDITORIAL_BACKTEST_SAMPLE_DAYS = int(os.getenv("EDITORIAL_BACKTEST_SAMPLE_DAYS", "365"))
FEEDBACK_WEEKLY_LOOKBACK_DAYS = int(os.getenv("FEEDBACK_WEEKLY_LOOKBACK_DAYS", "30"))
FEEDBACK_WEEKLY_MIN_TOPICS = int(os.getenv("FEEDBACK_WEEKLY_MIN_TOPICS", "5"))
FEEDBACK_WEEKLY_MIN_SAMPLES = int(os.getenv("FEEDBACK_WEEKLY_MIN_SAMPLES", "3"))
FEEDBACK_WEEKLY_MAX_TOPICS = int(os.getenv("FEEDBACK_WEEKLY_MAX_TOPICS", "100"))
FEEDBACK_WEEKLY_DIR = os.getenv(
    "FEEDBACK_WEEKLY_DIR",
    str(BASE_DIR / "data" / "feedback_weekly"),
)
FEEDBACK_WEEKLY_PENDING_PATCH_PATH = os.getenv(
    "FEEDBACK_WEEKLY_PENDING_PATCH_PATH",
    str(Path(FEEDBACK_WEEKLY_DIR) / "pending_latest.json"),
)

# HTTP timeouts + retries
EXT_TIMEOUT = float(os.getenv("EXT_TIMEOUT", "30"))
INT_TIMEOUT = float(os.getenv("INT_TIMEOUT", "15"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "2"))
RETRY_BASE_SLEEP = float(os.getenv("RETRY_BASE_SLEEP", "0.5"))

# Platforms
PLATFORMS = ["douyin", "xiaohongshu", "shipinhao"]


def is_mock_mode() -> bool:
    return os.getenv("MOCK_MODE", "0") == "1"


def require_env() -> None:
    if is_mock_mode():
        return
    missing = []
    if not any([GEMINI_API_KEY, QWEN_API_KEY, DEEPSEEK_API_KEY, ANALYZE_API_KEY]):
        missing.append("GEMINI_API_KEY or QWEN_API_KEY or DEEPSEEK_API_KEY or ANALYZE_API_KEY")
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")


def today_str() -> str:
    return date.today().isoformat()


def load_topic_clusters() -> list[dict]:
    try:
        with open(TOPIC_CLUSTERS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return [{"label": "unknown_cluster", "aliases": ["unknown_cluster"]}]
