from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore')
    host: str = '127.0.0.1'
    port: int = 8000
    storage_path: Path = ROOT / 'storage'
    database_path: Path = ROOT / 'data/rootdrive.db'
    internal_path: Path = ROOT / 'data/internal'
    auth_enabled: bool = False
    enable_public_shares: bool = False
    cookie_secure: bool = False
    max_upload_size_mb: int = 2048
    session_hours: int = 24
    max_preview_pixels: int = 50000000
    preview_cache_size_mb: int = 512

    def prepare(self) -> None:
        self.storage_path = (ROOT / self.storage_path).resolve()
        self.database_path = (ROOT / self.database_path).resolve()
        self.internal_path = (ROOT / self.internal_path).resolve()
        for protected in [self.database_path, self.internal_path, ROOT / 'backend', ROOT / 'frontend', ROOT / '.env']:
            if protected == self.storage_path or self.storage_path in protected.parents:
                raise ValueError('Storage must be separate from application and internal data')
        if self.max_upload_size_mb < 1:
            raise ValueError('Upload limit must be positive')
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        (self.internal_path / 'trash').mkdir(parents=True, exist_ok=True)
        (self.internal_path / 'uploads').mkdir(parents=True, exist_ok=True)
