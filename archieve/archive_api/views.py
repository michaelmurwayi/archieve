# archive_api/views.py
from rest_framework import generics
from .models import ArchievedFile
from .serializers import ArchievedFileSerializer

class ArchievedFileList(generics.ListAPIView):
    queryset = ArchievedFile.objects.all()
    serializer_class = ArchievedFileSerializer