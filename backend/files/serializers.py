from rest_framework import serializers
from .models import File

class FileSerializer(serializers.ModelSerializer):
    class Meta:
        model = File
        fields = ['id', 'file', 'original_filename', 'file_type', 'size', 'uploaded_at', 'file_hash', 'owner', 'is_duplicate', 'original_file_ref']
        read_only_fields = ['id', 'uploaded_at', 'file_hash', 'owner', 'is_duplicate', 'original_file_ref']

    def to_representation(self, instance):
        data = super().to_representation(instance)

        # If this is a duplicate, return the original file's path
        if instance.is_duplicate and instance.original_file_ref:
            # Use the original file's path directly
            data['file'] = instance.original_file_ref.file.url if instance.original_file_ref.file else None

        return data