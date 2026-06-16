from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    ForeignKey,
    Boolean,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Session(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True)
    site = Column(String, nullable=False)
    session_code = Column(String, nullable=False, unique=True)

    nickname = Column(String)
    game_type = Column(String)
    currency = Column(String, default="EUR")
    sb = Column(Float)
    bb = Column(Float)
    table_name = Column(String)
    start_date = Column(String)
    duration = Column(String)
    game_count = Column(Integer)

    hands = relationship("Hand", back_populates="session", cascade="all, delete-orphan")


class Hand(Base):
    __tablename__ = "hands"

    id = Column(Integer, primary_key=True)
    site_hand_id = Column(String, nullable=False, unique=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False)

    started_at = Column(String)
    max_players = Column(Integer)
    button_seat = Column(Integer)
    variant = Column(String, default="NLHE")
    currency = Column(String, default="EUR")
    sb = Column(Float)
    bb = Column(Float)

    session = relationship("Session", back_populates="hands")
    players = relationship("HandPlayer", back_populates="hand", cascade="all, delete-orphan")
    actions = relationship("Action", back_populates="hand", cascade="all, delete-orphan")
    board = relationship("Board", back_populates="hand", uselist=False, cascade="all, delete-orphan")
    hole_cards = relationship("HoleCards", back_populates="hand", cascade="all, delete-orphan")


class HandPlayer(Base):
    __tablename__ = "hand_players"

    id = Column(Integer, primary_key=True)
    hand_id = Column(Integer, ForeignKey("hands.id"), nullable=False)
    player_name = Column(String, nullable=False)

    seat = Column(Integer)
    is_dealer = Column(Boolean)
    stack_start = Column(Float)
    bet_total = Column(Float)
    win_total = Column(Float)
    rake = Column(Float)
    cashout = Column(Boolean)
    cashout_fee = Column(Float)

    hand = relationship("Hand", back_populates="players")

    __table_args__ = (
        UniqueConstraint("hand_id", "player_name", name="uq_hand_player"),
        Index("idx_hand_players_player", "player_name"),
    )


class Action(Base):
    __tablename__ = "actions"

    id = Column(Integer, primary_key=True)
    hand_id = Column(Integer, ForeignKey("hands.id"), nullable=False)

    street = Column(Integer, nullable=False)
    seq = Column(Integer, nullable=False)
    player_name = Column(String, nullable=False)

    action_type_code = Column(Integer, nullable=False)
    action = Column(String, nullable=False)
    amount = Column(Float, nullable=False, default=0.0)

    hand = relationship("Hand", back_populates="actions")

    __table_args__ = (
        UniqueConstraint("hand_id", "street", "seq", name="uq_action_order"),
        Index("idx_actions_player", "player_name"),
        Index("idx_actions_hand_street", "hand_id", "street"),
    )


class Board(Base):
    __tablename__ = "boards"
    hand_id = Column(Integer, ForeignKey("hands.id"), primary_key=True)

    flop1 = Column(String)
    flop2 = Column(String)
    flop3 = Column(String)
    turn = Column(String)
    river = Column(String)

    hand = relationship("Hand", back_populates="board")


class HoleCards(Base):
    __tablename__ = "hole_cards"

    id = Column(Integer, primary_key=True)
    hand_id = Column(Integer, ForeignKey("hands.id"), nullable=False)
    player_name = Column(String, nullable=False)

    card1 = Column(String)
    card2 = Column(String)
    is_known = Column(Boolean, default=False)

    hand = relationship("Hand", back_populates="hole_cards")

    __table_args__ = (
        UniqueConstraint("hand_id", "player_name", name="uq_holecards_hand_player"),
    )
