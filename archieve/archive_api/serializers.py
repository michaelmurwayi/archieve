# archive_api/serializers.py
from rest_framework import serializers
from .models import ArchievedFile

class ArchievedFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = ArchievedFile
        fields = "__all__"