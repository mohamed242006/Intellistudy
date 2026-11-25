from fastapi import APIRouter

from backend.app.api.v1 import attempts, auth, chat, courses, documents, generation, health

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(auth.router)
router.include_router(courses.router)
router.include_router(documents.router)
router.include_router(chat.router)
router.include_router(generation.router)
router.include_router(attempts.router)
