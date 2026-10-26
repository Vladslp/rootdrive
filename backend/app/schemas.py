from pydantic import BaseModel, Field


class FolderInput(BaseModel):
    path: str = ''
    name: str = Field(min_length=1, max_length=240)


class CreateFileInput(BaseModel):
    path: str = Field(default="", max_length=4096)
    name: str = Field(min_length=1, max_length=240)


class RenameInput(BaseModel):
    path: str
    name: str = Field(min_length=1, max_length=240)


class MoveInput(BaseModel):
    path: str
    destination: str = ''


class PathInput(BaseModel):
    path: str


class TrashInput(BaseModel):
    id: str


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=1024)


class UserInput(LoginInput):
    password: str = Field(min_length=10, max_length=1024)
    role: str = Field(default='user', pattern='^(user|admin)$')


class ShareInput(BaseModel):
    path: str
    expires_hours: int | None = Field(default=24, ge=1, le=8760)


class FileEntry(BaseModel):
    name: str
    path: str
    type: str
    size: int
    child_count: int | None = None
    modified: float
    mime: str
    favorite: bool = False
    tags: list[dict[str, str]] = Field(default_factory=list)
    color: str | None = None
    version_count: int = 0


class FileListing(BaseModel):
    items: list[FileEntry]
    total: int
    offset: int
    limit: int
    path: str


class StorageStats(BaseModel):
    file_count: int
    stored_bytes: int
    disk_free: int
    disk_total: int
    disk_used: int
    system_bytes: int
    trash_bytes: int
    versions_bytes: int
    uploads_bytes: int
    cache_bytes: int
    exports_bytes: int
    disk_percent: float
    categories: dict[str, int]


class BatchInput(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=200)
    destination: str = ''


class FavoriteInput(BatchInput):
    favorite: bool = True


class TagInput(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    color: str = Field(default='blue', pattern='^(blue|green|amber|rose|violet|slate)$')


class ItemTagsInput(BatchInput):
    tag_ids: list[str] = Field(default_factory=list, max_length=30)
    mode: str = Field(default='replace', pattern='^(replace|add)$')
    color: str | None = Field(default=None, pattern='^(folder|lavender|yellow|mint)$')


class UploadInput(BaseModel):
    path: str = ''
    relative_path: str = Field(min_length=1, max_length=4096)
    size: int = Field(ge=0)
    last_modified: float = Field(default=0, ge=0)
    source_name: str = Field(default='', max_length=240)
    overwrite: bool = False


class SettingsInput(BaseModel):
    max_upload_size_mb: int = Field(ge=1, le=1048576, strict=True)
