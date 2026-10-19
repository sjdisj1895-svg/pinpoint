from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class TimeWindow(str, Enum):
    MORNING = "MORNING"
    AFTERNOON = "AFTERNOON"
    EVENING = "EVENING"
    NIGHT = "NIGHT"
    ALL_DAY = "ALL_DAY"


class Transport(str, Enum):
    PUBLIC = "PUBLIC"
    CAR = "CAR"
    WALK = "WALK"


class BudgetTier(str, Enum):
    LOW = "LOW"
    MID = "MID"
    HIGH = "HIGH"


class Category(str, Enum):
    FESTIVAL = "FESTIVAL"
    FLEA_MARKET = "FLEA_MARKET"
    MOVIE = "MOVIE"
    TRAVEL_SPOT = "TRAVEL_SPOT"
    NEW_OPEN = "NEW_OPEN"


class Coords(BaseModel):
    lat: float = Field(ge=33.0, le=39.0)  # 대한민국 범위
    lng: float = Field(ge=124.0, le=132.0)


class TargetRegion(BaseModel):
    province: str
    city_district: str
    center_coords: Coords
    radius_km: float = Field(gt=0, le=100)


class TimeContext(BaseModel):
    target_date: date
    time_window: TimeWindow
    require_open_now: bool


class UserPersona(BaseModel):
    companion: str
    transport: Transport
    vibe_keywords: list[str]
    activity_level: int = Field(ge=1, le=5)
    budget_tier: BudgetTier


class T1Result(BaseModel):
    target_region: TargetRegion
    time_context: TimeContext
    user_persona: UserPersona
    requested_categories: list[Category]
    search_queries: list[str]


class UserProfile(BaseModel):
    """선택적 기본 프로필."""

    age_group: str | None = None
    home_region: str | None = None
    preferences: list[str] = []


class ParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    profile: UserProfile | None = None
    today: date | None = None  # 테스트용 오버라이드, 기본은 서버 날짜


class LiveStatus(str, Enum):
    OPEN_NOW = "OPEN_NOW"
    OPEN_SOON = "OPEN_SOON"
    CLOSED = "CLOSED"


class IndoorOutdoor(str, Enum):
    INDOOR = "INDOOR"
    OUTDOOR = "OUTDOOR"
    BOTH = "BOTH"


class SpotLocation(BaseModel):
    address: str = Field(min_length=1)
    lat: float = Field(ge=33.0, le=39.0)
    lng: float = Field(ge=124.0, le=132.0)
    region_tag: str


class SpotSchedule(BaseModel):
    period: str
    operating_hours: str
    live_status: LiveStatus
    movie_showtimes: list[str] | None = None


class SpotAttributes(BaseModel):
    vibe_tags: list[str]
    admission_fee: str
    parking_available: bool | None = None  # None = 확인되지 않음
    indoor_outdoor: IndoorOutdoor


class Spot(BaseModel):
    id: str
    category: Category
    title: str
    subtitle: str
    location: SpotLocation
    schedule: SpotSchedule
    attributes: SpotAttributes
    source_url: str
    image_url: str | None = None  # 대표 사진 (한국관광공사 TourAPI 제공 등)
    confidence_score: float = Field(ge=0, le=1)
    verification_note: str


class DurationType(str, Enum):
    HALF_DAY = "HALF_DAY"
    FULL_DAY = "FULL_DAY"


class PinItem(BaseModel):
    spot_id: str
    category: Category
    score: int = Field(ge=0, le=100)
    why_for_you: str
    tips: list[str] = []


class CourseStop(BaseModel):
    order: int = Field(ge=1)
    spot_id: str
    suggested_time: str
    why_for_you: str
    tips: list[str] = []
    distance_from_prev_km: float | None = None  # 코드에서 계산


class Course(BaseModel):
    course_id: str
    title: str
    duration_type: DurationType
    score: int = Field(ge=0, le=100)
    why_for_you: str
    stops: list[CourseStop] = Field(min_length=2, max_length=4)


class T3Result(BaseModel):
    pin_list: list[PinItem]
    courses: list[Course]


class Weather(str, Enum):
    CLEAR = "CLEAR"
    RAIN = "RAIN"
    HEAT = "HEAT"


class Trigger(str, Enum):
    WEATHER = "WEATHER"
    DELAY = "DELAY"
    FEEDBACK = "FEEDBACK"
    CROWD = "CROWD"
    EVENT_END = "EVENT_END"


class RerouteRequest(BaseModel):
    feedback: str = Field(min_length=1, max_length=1000)
    location: Coords  # 사용자 현재 위치
    now: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")  # HH:MM, 기본은 서버 시각
    weather: Weather | None = None
    radius_km: float = Field(default=3.0, gt=0, le=30)
    t1: T1Result
    spots: list[Spot]  # T2 결과 풀
    course: Course | None = None  # 현재 따르는 코스


class PersonaPatch(BaseModel):
    vibe_keywords: list[str] | None = None
    activity_level: int | None = Field(default=None, ge=1, le=5)
    budget_tier: BudgetTier | None = None
    preference_notes: list[str] = []


class Replacement(BaseModel):
    removed_spot_id: str | None = None
    added_spot_id: str | None = None
    reason: str


class T5Raw(BaseModel):
    """모델 원본 출력."""

    trigger: Trigger
    summary: str
    persona_patch: PersonaPatch
    replacements: list[Replacement]
    course: Course | None
    pin_list: list[PinItem]


class RerouteResponse(BaseModel):
    trigger: Trigger
    summary: str
    persona: UserPersona  # 패치가 반영된 user_persona
    preference_notes: list[str]
    replacements: list[Replacement]
    course: Course | None
    pin_list: list[PinItem]
    markers: dict  # GeoJSON FeatureCollection (Point)
    route: dict | None  # GeoJSON Feature (LineString)
