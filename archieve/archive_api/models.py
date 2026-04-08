# archive_api/models.py
from django.db import models

class ArchievedFile(models.Model):
    group_name = models.CharField(max_length=100)
    username = models.CharField(max_length=100)
    source_path = models.TextField()
    archive_path = models.TextField()
    status = models.CharField(max_length=20)
    error_message = models.TextField(blank=True, null=True)
    archived_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "archived_files"
        ordering = ["-archived_at"]

    def __str__(self):
        return f"{self.username} - {self.source_path} -> {self.archive_path}"