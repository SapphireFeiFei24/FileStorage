from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import FileViewSet, login_view, logout_view, api_root, storage_stats

router = DefaultRouter()
router.register(r'files', FileViewSet, basename='File')

urlpatterns = [
    path('', include(router.urls)),
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('info/', api_root, name='api-root'),  # Public endpoint for API info
    path('storage_stats/', storage_stats, name='storage-stats'),  # Storage statistics endpoint
] 