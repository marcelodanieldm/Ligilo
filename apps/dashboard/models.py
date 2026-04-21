from dataclasses import dataclass


@dataclass(frozen=True)
class LeaderIdentity:
    initial: str


@dataclass(frozen=True)
class NavItem:
    label: str
    href: str
    active: bool = False


@dataclass(frozen=True)
class ConnectivityStatus:
    note: str
    last_sync: str
    pending_messages: str


@dataclass(frozen=True)
class StatCard:
    label: str
    value: str
    caption: str
    tone: str
    emphasis: str = "normal"


@dataclass(frozen=True)
class FunnelStep:
    badge: str
    title: str
    description: str
    value: str
    highlight: bool = False


@dataclass(frozen=True)
class FeaturedMission:
    title: str
    status: str
    objective: str
    channel: str
    response: str
    note: str


@dataclass(frozen=True)
class LeaderTask:
    title: str
    description: str
    tag: str
    tag_tone: str


@dataclass(frozen=True)
class PatrolStatus:
    name: str
    status_dot: str
    summary: str


@dataclass(frozen=True)
class DashboardPageModel:
    lang: str
    leader: LeaderIdentity
    nav_items: list[NavItem]
    connectivity: ConnectivityStatus
    hero_copy: str
    stats: list[StatCard]
    funnel_steps: list[FunnelStep]
    featured_mission: FeaturedMission
    tasks: list[LeaderTask]
    patrols: list[PatrolStatus]