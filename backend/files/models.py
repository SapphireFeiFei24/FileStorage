import os
import hashlib
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.contrib.auth.models import User
import uuid


def file_upload_path(instance, filename):
    """Generate file path for new file upload"""
    ext = filename.split('.')[-1]
    filename = f"{uuid.uuid4()}.{ext}"
    return os.path.join('uploads', filename)


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    storage_limit_mb = models.IntegerField(default=10)  # Default 10 MB storage limit
    api_calls_per_second = models.IntegerField(default=2)  # Default 2 API calls per second

    def __str__(self):
        return f"{self.user.username}'s Profile"


class File(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    file = models.FileField(upload_to=file_upload_path)
    original_filename = models.CharField(max_length=255)
    file_type = models.CharField(max_length=100)
    size = models.BigIntegerField()
    uploaded_at = models.DateTimeField(auto_now_add=True)
    file_hash = models.CharField(max_length=64, unique=True, null=True, blank=True)  # SHA-256 hash
    owner = models.ForeignKey(User, on_delete=models.CASCADE)  # Associate with user (required)

    class Meta:
        ordering = ['-uploaded_at']

    def calculate_file_hash(self):
        """Calculate SHA-256 hash of the file content"""
        if not self.file:
            return None

        sha256_hash = hashlib.sha256()
        # Open the file and read it in chunks to handle large files efficiently
        with self.file.open('rb') as f:
            # Read the file in chunks to avoid memory issues with large files
            for chunk in iter(lambda: f.read(4096), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

    def __str__(self):
        return self.original_filename


# Signal to delete the file from filesystem when the model instance is deleted
@receiver(post_delete, sender=File)
def delete_file_from_storage(sender, instance, **kwargs):
    if instance.file:
        if os.path.isfile(instance.file.path):
            os.remove(instance.file.path)


# Signal to create user profile when a user is created
@receiver(models.signals.post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)