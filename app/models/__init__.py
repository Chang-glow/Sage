from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


from app.models.agent import ActivityLog, Agent, AgentDailySchedule, AgentSchedule  # noqa: E402, F401
from app.models.bar import Bar, BarMember, BarModLog, BarRule, AgentBarLevel, Election  # noqa: E402, F401
from app.models.external_topic import Topic  # noqa: E402, F401
from app.models.notification import Notification  # noqa: E402, F401
from app.models.post import Post, Reply  # noqa: E402, F401
from app.models.relationship import Relationship  # noqa: E402, F401
from app.models.skill_group import SkillGroup, SkillGroupMember  # noqa: E402, F401
from app.models.slang import AgentSlang, Slang  # noqa: E402, F401
from app.models.social import Bookmark, Follow, Like, PrivateMessage  # noqa: E402, F401
from app.models.world_book import WorldBookEntry  # noqa: E402, F401
