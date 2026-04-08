# archive_api/urls.py
from django.urls import path
from .views import ArchievedFileList

urlpatterns = [
    path('archived-files/', ArchievedFileList.as_view(), name='archived-files'),
]