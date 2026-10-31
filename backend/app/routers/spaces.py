import uuid
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from ..database import Space, SpaceMember, UploadJob, User
from ..services.security import require_access

router = APIRouter(prefix='/api/spaces')


def signed_in(request, user):
    if not request.app.state.settings.auth_enabled or not user:
        raise HTTPException(403, 'Enable sign-in to use personal spaces')


def owned(db, identifier, user):
    space = db.get(Space, identifier)
    if not space or space.owner_id != user['id'] or space.kind != 'shared':
        raise HTTPException(403, 'Only the shared space owner can manage members')
    return space


@router.get('')
def spaces(request: Request, user=Depends(require_access)):
    registry = request.app.state.spaces
    if not request.app.state.settings.auth_enabled:
        return {'items': [registry.describe(None, 'shared', None)], 'active': 'shared'}
    personal = registry.personal(user['id'])
    with request.app.state.db() as db:
        membership = select(SpaceMember.space_id).where(SpaceMember.user_id == user['id'])
        values = list(db.scalars(select(Space).where(or_(Space.owner_id == user['id'], Space.id.in_(membership))).order_by(Space.created_at)))
        items = [registry.describe(db, 'shared', user['id'])] + [registry.describe(db, space.id, user['id']) for space in values]
        return {'items': items, 'active': request.cookies.get('rootdrive_space', 'shared'), 'personal': personal}


class SpaceInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)


@router.post('', status_code=201)
def create_space(body: SpaceInput, request: Request, user=Depends(require_access)):
    signed_in(request, user)
    name = body.name.strip()
    if not name or any(ord(value) < 32 for value in name):
        raise HTTPException(422, 'Give the space a valid name')
    with request.app.state.spaces.lock, request.app.state.db() as db:
        count = db.scalar(select(func.count()).select_from(Space).where(Space.owner_id == user['id'], Space.kind == 'shared'))
        if count >= 20:
            raise HTTPException(409, 'You can own up to 20 shared spaces')
        space = Space(id=uuid.uuid4().hex, name=name, kind='shared', owner_id=user['id'])
        db.add(space)
        db.commit()
        return request.app.state.spaces.describe(db, space.id, user['id'])


class SelectInput(BaseModel):
    id: str = Field(min_length=1, max_length=32)


@router.post('/select')
def select_space(body: SelectInput, request: Request, response: Response, user=Depends(require_access)):
    signed_in(request, user)
    registry = request.app.state.spaces
    with request.app.state.db() as db:
        space = registry.describe(db, body.id, user['id'])
    try:
        current = registry.selected(request, user['id'])
        context = registry.context(current['id'])
        with context.db() as db:
            pending = db.scalar(select(func.count()).select_from(UploadJob).where(UploadJob.owner == str(user['id']), UploadJob.status == 'open'))
            if pending:
                raise HTTPException(409, 'Finish or cancel uploads before switching spaces')
    except HTTPException as error:
        if error.status_code not in {403, 404}:
            raise
    registry.context(space['id'])
    response.set_cookie('rootdrive_space', body.id, httponly=True, secure=request.app.state.settings.cookie_secure, samesite='strict', path='/')
    return space


@router.get('/{identifier}/members')
def members(identifier: str, request: Request, user=Depends(require_access)):
    signed_in(request, user)
    with request.app.state.db() as db:
        space = owned(db, identifier, user)
        owner = db.get(User, space.owner_id)
        items = [{'id': owner.id, 'username': owner.username, 'role': 'owner'}]
        for member, account in db.execute(select(SpaceMember, User).join(User, User.id == SpaceMember.user_id).where(SpaceMember.space_id == identifier)):
            items.append({'id': account.id, 'username': account.username, 'role': member.role})
        return {'items': items}


class MemberInput(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    role: Literal['reader', 'editor']


@router.post('/{identifier}/members')
def add_member(identifier: str, body: MemberInput, request: Request, user=Depends(require_access)):
    signed_in(request, user)
    with request.app.state.db() as db:
        space = owned(db, identifier, user)
        account = db.scalar(select(User).where(User.username == body.username))
        if not account:
            raise HTTPException(404, 'Account not found')
        if account.id == space.owner_id:
            raise HTTPException(409, 'The owner already has full access')
        member = db.get(SpaceMember, (identifier, account.id))
        if member:
            member.role = body.role
        else:
            db.add(SpaceMember(space_id=identifier, user_id=account.id, role=body.role))
        db.commit()
    return {'ok': True}


@router.delete('/{identifier}/members/{user_id}')
def remove_member(identifier: str, user_id: int, request: Request, user=Depends(require_access)):
    signed_in(request, user)
    with request.app.state.db() as db:
        owned(db, identifier, user)
        member = db.get(SpaceMember, (identifier, user_id))
        if member:
            db.delete(member)
            db.commit()
    return {'ok': True}
