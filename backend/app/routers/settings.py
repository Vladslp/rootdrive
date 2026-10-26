from fastapi import APIRouter, Depends, HTTPException, Request
from ..database import ApplicationSetting
from ..schemas import SettingsInput
from ..services.security import require_access

router = APIRouter(prefix='/api/settings')


@router.get('')
def server_settings(request: Request, user=Depends(require_access)):
    return {'max_upload_size_mb': request.app.state.settings.max_upload_size_mb}


@router.patch('')
def update_settings(body: SettingsInput, request: Request, user=Depends(require_access)):
    if request.app.state.settings.auth_enabled and (not user or user['role'] != 'admin'):
        raise HTTPException(403, 'Administrator access required')
    with request.app.state.fs.lock, request.app.state.db() as db:
        setting = db.get(ApplicationSetting, 'max_upload_size_mb')
        if setting is None:
            db.add(ApplicationSetting(key='max_upload_size_mb', value=str(body.max_upload_size_mb)))
        else:
            setting.value = str(body.max_upload_size_mb)
        db.commit()
        request.app.state.settings.max_upload_size_mb = body.max_upload_size_mb
    return {'max_upload_size_mb': body.max_upload_size_mb}
