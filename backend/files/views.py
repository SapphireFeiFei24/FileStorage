from django.shortcuts import render
from rest_framework import viewsets, status, views
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.decorators import api_view, permission_classes
from .models import File, UserProfile
from .serializers import FileSerializer
from io import BytesIO
from django.core.files.uploadedfile import SimpleUploadedFile
import hashlib

# Create your views here.

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.utils.decorators import method_decorator


@api_view(['GET'])
def api_root(request):
    """
    Root endpoint for the API.
    """
    content = {
        'message': 'Welcome to the File Vault API',
        'files': 'GET/POST /api/files/ (requires authentication)',
        'storage_stats': 'GET /api/files/storage_stats/ (requires authentication)',
    }
    return Response(content)

@api_view(['GET'])
def storage_stats(request):
    # Get storage statistics for the authenticated user
    if not request.user.is_authenticated:
        return Response({'detail': 'Authentication required'}, status=status.HTTP_401_UNAUTHORIZED)

    # Get user's profile (create if doesn't exist)
    profile, created = UserProfile.objects.get_or_create(
        user=request.user,
        defaults={'storage_limit_mb': 10, 'api_calls_per_second': 2, 'current_storage_used': 0}
    )

    # Get all files for the current user
    user_files = File.objects.filter(owner=request.user)

    # Calculate original storage (sum of all file sizes)
    original_storage_used = sum(file.size for file in user_files)

    # Use the stored current_storage_used value which represents logical storage usage
    # (sum of all files regardless of duplication)
    total_storage_used = profile.current_storage_used

    # Since current_storage_used represents logical usage (sum of all files),
    # there are no storage savings to calculate in this model
    # The actual storage used after deduplication would need to be calculated separately
    actual_storage_after_deduplication = 0
    unique_hashes = {}
    for file in user_files:
        if file.file_hash and file.file_hash not in unique_hashes:
            unique_hashes[file.file_hash] = file.size
    actual_storage_after_deduplication = sum(unique_hashes.values())

    # Calculate storage savings
    storage_savings = original_storage_used - actual_storage_after_deduplication

    # Calculate savings percentage
    savings_percentage = 0
    if original_storage_used > 0:
        savings_percentage = (storage_savings / original_storage_used) * 100

    # Get user's storage limit in bytes
    storage_limit_bytes = profile.storage_limit_mb * 1024 * 1024

    return Response({
        'total_storage_used': actual_storage_after_deduplication,  # Actual storage used after deduplication
        'original_storage_used': original_storage_used,  # Logical storage without deduplication
        'storage_savings': storage_savings,
        'savings_percentage': round(savings_percentage, 2),
        'storage_limit_bytes': storage_limit_bytes,
        'storage_usage_percentage': round((profile.current_storage_used / storage_limit_bytes) * 100, 2) if storage_limit_bytes > 0 else 0  # Based on logical usage
    })

class FileViewSet(viewsets.ModelViewSet):
    serializer_class = FileSerializer
    permission_classes = [IsAuthenticated]  # Require authentication

    def get_queryset(self):
        # Start with the user's files
        queryset = File.objects.filter(owner=self.request.user) if self.request.user.is_authenticated else File.objects.none()

        # Define filter mappings: parameter name -> (field lookup, transform function)
        filters = {
            'search': ('original_filename__icontains', None),
            'file_type': ('file_type__icontains', None),
            'min_size': ('size__gte', self._safe_int_conversion),
            'max_size': ('size__lte', self._safe_int_conversion),
            'start_date': ('uploaded_at__gte', self._parse_iso_datetime),
            'end_date': ('uploaded_at__lte', self._parse_iso_datetime),
        }

        # Apply filters based on query parameters
        for param_name, (field_lookup, transform_fn) in filters.items():
            param_value = self.request.query_params.get(param_name, None)
            if param_value is not None:
                if transform_fn:
                    transformed_value = transform_fn(param_value)
                    if transformed_value is not None:  # Only apply filter if transformation was successful
                        queryset = queryset.filter(**{field_lookup: transformed_value})
                else:
                    queryset = queryset.filter(**{field_lookup: param_value})

        return queryset

    def _safe_int_conversion(self, value):
        """Safely convert a string value to integer, returning None if conversion fails."""
        try:
            return int(value)
        except ValueError:
            return None

    def _parse_iso_datetime(self, value):
        """Parse ISO 8601 datetime string, returning None if parsing fails."""
        from django.utils.dateparse import parse_datetime
        return parse_datetime(value)

    def create(self, request, *args, **kwargs):
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'No file provided'}, status=status.HTTP_400_BAD_REQUEST)

        # Get user's profile (create if doesn't exist)
        profile, created = UserProfile.objects.get_or_create(
            user=request.user,
            defaults={'storage_limit_mb': 10, 'api_calls_per_second': 2, 'current_storage_used': 0}
        )

        # Check if the new file would exceed storage quota
        storage_limit_bytes = profile.storage_limit_mb * 1024 * 1024
        if profile.current_storage_used + file_obj.size > storage_limit_bytes:
            return Response(
                {'error': 'Storage Quota Exceeded'},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

        # Calculate hash of the incoming file to check for duplicates
        sha256_hash = hashlib.sha256()

        # Read the file in chunks to calculate hash and store content temporarily
        file_content = BytesIO()
        for chunk in file_obj.chunks():
            sha256_hash.update(chunk)
            file_content.write(chunk)

        file_hash = sha256_hash.hexdigest()

        # Check if a file with the same hash already exists for this user
        existing_file = File.objects.filter(owner=request.user, file_hash=file_hash).first()

        if existing_file:
            # Create a new record that points to the same physical file
            # Don't charge storage since it's a duplicate
            new_file_record = File.objects.create(
                original_filename=file_obj.name,
                file_type=file_obj.content_type,
                size=file_obj.size,
                file_hash=file_hash,
                owner=request.user,
                is_duplicate=True,
                original_file_ref=existing_file  # Point to the original file
                # Note: We don't set the file field for duplicates, it will be handled by the original
            )

            # For duplicates, we don't increase storage usage since it's already counted
            remaining_storage = storage_limit_bytes - profile.current_storage_used
            response_data = {
                'warning': f'We\'ve processed this upload. A file with the same content already exists as "{existing_file.original_filename}", but this new record is created separately.',
                'file': FileSerializer(new_file_record).data,
                'remaining_storage_bytes': remaining_storage,
                'storage_usage_percentage': round((profile.current_storage_used / storage_limit_bytes) * 100, 2) if storage_limit_bytes > 0 else 0
            }

            # Calculate headers for the new record
            from rest_framework.reverse import reverse
            location = reverse('File-detail', kwargs={'pk': new_file_record.pk}, request=request)
            headers = {'Location': location}

            return Response(response_data, status=status.HTTP_200_OK)

        # Reset the file pointer to the beginning for saving
        file_content.seek(0)

        # Create a new file-like object with the content we stored
        new_file_obj = SimpleUploadedFile(
            name=file_obj.name,
            content=file_content.getvalue(),
            content_type=file_obj.content_type
        )

        # Create the file record directly instead of using serializer
        file_record = File.objects.create(
            file=new_file_obj,
            original_filename=file_obj.name,
            file_type=file_obj.content_type,
            size=file_obj.size,
            file_hash=file_hash,
            owner=request.user
        )

        # Update the user's storage usage (add the new file's size)
        # This represents the logical storage usage (sum of all files regardless of duplication)
        profile.current_storage_used += file_obj.size
        profile.save(update_fields=['current_storage_used'])

        # Calculate remaining storage after successful upload
        remaining_storage = storage_limit_bytes - profile.current_storage_used

        # Serialize the created record
        serializer = FileSerializer(file_record)

        # Add storage info to the response
        response_data = serializer.data
        response_data['remaining_storage_bytes'] = remaining_storage
        response_data['storage_usage_percentage'] = round((profile.current_storage_used / storage_limit_bytes) * 100, 2) if storage_limit_bytes > 0 else 0

        headers = self.get_success_headers(serializer.data)
        return Response(response_data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_destroy(self, instance):
        # Update storage usage when a file is deleted
        profile = instance.owner.profile

        # Subtract the file's size from the user's storage usage
        # This represents the logical storage usage (sum of all files regardless of duplication)
        profile.current_storage_used -= instance.size
        if profile.current_storage_used < 0:
            profile.current_storage_used = 0  # Prevent negative storage usage

        profile.save(update_fields=['current_storage_used'])

        # Call the parent method to actually delete the instance
        super().perform_destroy(instance)
