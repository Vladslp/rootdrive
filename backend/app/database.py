import time
from sqlalchemy import String, Integer, Float, ForeignKey, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String, default='user')
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Session(Base):
    __tablename__ = 'sessions'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    session_hash: Mapped[str] = mapped_column(String, unique=True)
    csrf_token: Mapped[str] = mapped_column(String)
    expires_at: Mapped[float] = mapped_column(Float)


class TrashItem(Base):
    __tablename__ = 'trash_items'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    original_path: Mapped[str] = mapped_column(String)
    stored_path: Mapped[str] = mapped_column(String)
    deleted_at: Mapped[float] = mapped_column(Float, default=time.time)
    item_type: Mapped[str] = mapped_column(String)
    size: Mapped[int] = mapped_column(Integer, default=0)


class Share(Base):
    __tablename__ = 'shares'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    file_path: Mapped[str] = mapped_column(String)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    expires_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    revoked_at: Mapped[float | None] = mapped_column(Float, nullable=True)


def create_database(path):
    engine = create_engine(f'sqlite:///{path}', connect_args={'check_same_thread': False, 'timeout': 30})

    @event.listens_for(engine, 'connect')
    def configure(connection, record):
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('PRAGMA foreign_keys=ON')

    Base.metadata.create_all(engine)
    return engine, sessionmaker(engine, expire_on_commit=False)
