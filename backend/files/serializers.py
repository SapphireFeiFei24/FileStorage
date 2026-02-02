from rest_framework import serializers
from .models import File

class FileSerializer(serializers.ModelSerializer):
    user_id = serializers.SerializerMethodField()
    reference_count = serializers.SerializerMethodField()
    is_reference = serializers.SerializerMethodField()
    original_file = serializers.SerializerMethodField()

    class Meta:
        model = File
        fields = ['id', 'file', 'original_filename', 'file_type', 'size', 'uploaded_at', 'file_hash', 'user_id', 'reference_count', 'is_reference', 'original_file']
        read_only_fields = ['id', 'uploaded_at', 'file_hash']

    def get_user_id(self, obj):
        return obj.owner.id

    def get_reference_count(self, obj):
        if obj.is_duplicate:
            # If this is a duplicate, count references to the original
            return File.objects.filter(original_file_ref=obj.original_file_ref).count()
        else:
            # If this is an original, count how many duplicates reference it plus itself
            duplicate_count = File.objects.filter(original_file_ref=obj).count()
            return duplicate_count + 1

    def get_is_reference(self, obj):
        return obj.is_duplicate

    def get_original_file(self, obj):
        if obj.is_duplicate and obj.original_file_ref:
            return str(obj.original_file_ref.id)
        return None

    def to_representation(self, instance):
        data = super().to_representation(instance)

        # If this is a duplicate, return the original file's path
        if instance.is_duplicate and instance.original_file_ref:
            # Use the original file's path directly
            data['file'] = instance.original_file_ref.file.url if instance.original_file_ref.file else None

        return data