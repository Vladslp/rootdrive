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
