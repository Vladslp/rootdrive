from pydantic import BaseModel, Field


class FolderInput(BaseModel):
    path: str = ''
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
    modified: float
    mime: str


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
    disk_percent: float
    categories: dict[str, int]
