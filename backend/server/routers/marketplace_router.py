"""技能市场 API 路由"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from server.utils.auth_middleware import get_admin_user, get_db, get_required_user
from yuxi.marketplace.service import MarketplaceService
from yuxi.marketplace.repository import MarketplaceRepository
from yuxi.storage.postgres.models_business import User

router = APIRouter(prefix="/marketplace", tags=["marketplace"])


async def get_marketplace_service(
    db: AsyncSession = Depends(get_db),
) -> MarketplaceService:
    """获取市场服务依赖"""
    repo = MarketplaceRepository(db)
    return MarketplaceService(repo, db)


@router.get("/entries")
async def list_market_entries(
    source_type: Optional[str] = Query(None, description="来源类型: builtin | company"),
    category_id: Optional[int] = Query(None, description="分类 ID"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    service: MarketplaceService = Depends(get_marketplace_service),
    current_user: User = Depends(get_required_user),
):
    """获取市场条目列表"""
    result = await service.list_market_entries(
        source_type=source_type,
        category_id=category_id,
        page=page,
        page_size=page_size,
    )
    return {"success": True, **result}


@router.get("/entries/{slug}")
async def get_market_entry_detail(
    slug: str,
    service: MarketplaceService = Depends(get_marketplace_service),
    current_user: User = Depends(get_required_user),
):
    """获取市场条目详情"""
    result = await service.get_market_entry_detail(slug)
    if not result:
        raise HTTPException(status_code=404, detail="市场条目不存在")
    return {"success": True, "data": result}


@router.post("/entries/{slug}/install")
async def install_market_skill(
    slug: str,
    service: MarketplaceService = Depends(get_marketplace_service),
    current_user: User = Depends(get_required_user),
):
    """安装市场技能"""
    try:
        result = await service.install_skill(
            user_uid=current_user.uid,
            slug=slug,
        )
        return {"success": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/submissions/pending")
async def list_pending_submissions(
    service: MarketplaceService = Depends(get_marketplace_service),
    current_user: User = Depends(get_admin_user),
):
    """获取待审批列表（管理员）"""
    submissions = await service.repo.list_pending_submissions()
    return {"success": True, "data": [s.to_dict() for s in submissions]}


@router.post("/submissions")
async def submit_skill_to_market(
    body: dict,
    service: MarketplaceService = Depends(get_marketplace_service),
    current_user: User = Depends(get_required_user),
):
    """提交个人技能到市场"""
    required = ["original_skill_id", "title", "description", "change_type"]
    for field in required:
        if field not in body:
            raise HTTPException(status_code=400, detail=f"缺少必填字段: {field}")

    try:
        result = await service.submit_skill_to_market(
            original_skill_id=body["original_skill_id"],
            title=body["title"],
            description=body["description"],
            category_id=body.get("category_id"),
            submission_note=body.get("submission_note", ""),
            change_type=body["change_type"],
            submitter_uid=current_user.uid,
        )
        return {"success": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/submissions/{submission_id}/approve")
async def approve_submission(
    submission_id: int,
    body: dict,
    service: MarketplaceService = Depends(get_marketplace_service),
    current_user: User = Depends(get_admin_user),
):
    """审批通过"""
    try:
        result = await service.approve_submission(
            submission_id=submission_id,
            reviewer_uid=current_user.uid,
            review_note=body.get("review_note", ""),
        )
        return {"success": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/submissions/{submission_id}/reject")
async def reject_submission(
    submission_id: int,
    body: dict,
    service: MarketplaceService = Depends(get_marketplace_service),
    current_user: User = Depends(get_admin_user),
):
    """审批驳回"""
    try:
        result = await service.reject_submission(
            submission_id=submission_id,
            reviewer_uid=current_user.uid,
            review_note=body.get("review_note", ""),
        )
        return {"success": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/admin/entries/{slug}/unpublish")
async def unpublish_entry(
    slug: str,
    service: MarketplaceService = Depends(get_marketplace_service),
    current_user: User = Depends(get_admin_user),
):
    """下架技能（管理员）"""
    try:
        result = await service.unpublish_entry(slug=slug, admin_uid=current_user.uid)
        return {"success": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
