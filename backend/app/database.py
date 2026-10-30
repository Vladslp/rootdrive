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


class ItemMetadata(Base):
    __tablename__ = 'item_metadata'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    path: Mapped[str] = mapped_column(String, unique=True, index=True)
    color: Mapped[str | None] = mapped_column(String, nullable=True)


class Favorite(Base):
    __tablename__ = 'favorites'
    owner: Mapped[str] = mapped_column(String, primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey('item_metadata.id', ondelete='CASCADE'), primary_key=True)


class Tag(Base):
    __tablename__ = 'tags'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True)
    color: Mapped[str] = mapped_column(String, default='blue')


class ItemTag(Base):
    __tablename__ = 'item_tags'
    item_id: Mapped[str] = mapped_column(ForeignKey('item_metadata.id', ondelete='CASCADE'), primary_key=True)
    tag_id: Mapped[str] = mapped_column(ForeignKey('tags.id', ondelete='CASCADE'), primary_key=True)


class FileVersion(Base):
    __tablename__ = 'file_versions'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey('item_metadata.id', ondelete='CASCADE'), index=True)
    stored_path: Mapped[str] = mapped_column(String)
    size: Mapped[int] = mapped_column(Integer)
    modified: Mapped[float] = mapped_column(Float)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class UploadJob(Base):
    __tablename__ = 'upload_jobs'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner: Mapped[str] = mapped_column(String, index=True)
    path: Mapped[str] = mapped_column(String)
    size: Mapped[int] = mapped_column(Integer)
    received: Mapped[int] = mapped_column(Integer, default=0)
    last_modified: Mapped[float] = mapped_column(Float, default=0)
    source_name: Mapped[str] = mapped_column(String, default='')
    overwrite: Mapped[int] = mapped_column(Integer, default=0)
    original_mtime: Mapped[str | None] = mapped_column(String, nullable=True)
    original_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, default='open')
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time)


class ArchiveExport(Base):
    __tablename__ = 'archive_exports'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class ApplicationSetting(Base):
    __tablename__ = 'application_settings'
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String)


class Album(Base):
    __tablename__ = 'albums'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class AlbumItem(Base):
    __tablename__ = 'album_items'
    album_id: Mapped[str] = mapped_column(ForeignKey('albums.id', ondelete='CASCADE'), primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey('item_metadata.id', ondelete='CASCADE'), primary_key=True)


class ContentHash(Base):
    __tablename__ = 'content_hashes'
    path: Mapped[str] = mapped_column(String, primary_key=True)
    signature: Mapped[str] = mapped_column(String)
    digest: Mapped[str] = mapped_column(String)


class ShareProtection(Base):
    __tablename__ = 'share_protections'
    share_id: Mapped[str] = mapped_column(ForeignKey('shares.id', ondelete='CASCADE'), primary_key=True)
    password_hash: Mapped[str] = mapped_column(String)


class ShareGrant(Base):
    __tablename__ = 'share_grants'
    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    share_id: Mapped[str] = mapped_column(ForeignKey('shares.id', ondelete='CASCADE'), index=True)
    expires_at: Mapped[float] = mapped_column(Float)
