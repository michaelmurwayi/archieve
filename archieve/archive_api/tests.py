# archive_api/tests.py
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from .models import ArchievedFile

class ArchivedFileAPITest(TestCase):

    def setUp(self):
        self.client = APIClient()
        # Create test data
        ArchievedFile.objects.create(
            group_name="developers",
            username="alice",
            source_path="/home/alice/test.txt",
            archive_path="/archive/alice/test.txt",
            status="success"
        )

    def test_get_archived_files(self):
        url = reverse('archieved-files')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['username'], 'alice')