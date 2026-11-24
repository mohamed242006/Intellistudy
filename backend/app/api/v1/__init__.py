from fastapi import APIRouter

from backend.app.api.v1 import auth, courses, health

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(auth.router)
router.include_router(courses.router)
