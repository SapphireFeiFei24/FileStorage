from django.shortcuts import render
from django.contrib.auth import authenticate, login, logout
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

def login_view(request):
    if request.method == 'GET':
        # Render a login form for GET requests
        return render(request, 'login.html', {})
    elif request.method == 'POST':
        # Handle login for POST requests
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(username=username, password=password)
        if user:
            login(request, user)
            if request.accepts('application/json'):
                return JsonResponse({'detail': 'Login successful'})
            else:
                # Redirect or return a success page
                return render(request, 'login_success.html', {'user': user})
        else:
            if request.accepts('application/json'):
                return JsonResponse({'detail': 'Invalid credentials'}, status=401)
            else:
                return render(request, 'login.html', {'error': 'Invalid credentials'})

@api_view(['POST'])
def logout_view(request):
    logout(request)
    return Response({'detail': 'Logout successful'})

@api_view(['GET'])
@permission_classes([AllowAny])
def api_root(request):
    """
    Root endpoint for the API.
    """
    content = {
        'message': 'Welcome to the File Vault API',
        'login': 'POST /api/login/',
        'logout': 'POST /api/logout/',
        'files': 'GET/POST /api/files/ (requires authentication)',
        'storage_stats': 'GET /api/files/storage_stats/ (requires authentication)',
    }
    return Response(content)

@api_view(['GET'])
def storage_stats(request):
    # Get storage statistics for the authenticated user
    if not request.user.is_authenticated:
        return Response({'detail': 'Authentication required'}, status=status.HTTP_401_UNAUTHORIZED)

    # Get all files for the current user
    user_files = File.objects.filter(owner=request.user)

    # Calculate original storage (sum of all file sizes)
    original_storage_used = sum(file.size for file in user_files)

    # Calculate actual storage used after deduplication
    # Group files by hash and sum only unique files
    unique_hashes = {}
    for file in user_files:
        if file.file_hash and file.file_hash not in unique_hashes:
            unique_hashes[file.file_hash] = file.size

    total_storage_used = sum(unique_hashes.values())

    # Calculate storage savings
    storage_savings = original_storage_used - total_storage_used

    # Calculate savings percentage
    savings_percentage = 0
    if original_storage_used > 0:
        savings_percentage = (storage_savings / original_storage_used) * 100

    # Get user's storage limit in bytes
    try:
        storage_limit_bytes = request.user.profile.storage_limit_mb * 1024 * 1024
    except AttributeError:
        # If profile doesn't exist, create it with default limit
        profile, created = UserProfile.objects.get_or_create(user=request.user, defaults={'storage_limit_mb': 10})
        storage_limit_bytes = profile.storage_limit_mb * 1024 * 1024

    return Response({
        'total_storage_used': total_storage_used,
        'original_storage_used': original_storage_used,
        'storage_savings': storage_savings,
        'savings_percentage': round(savings_percentage, 2),
        'storage_limit_bytes': storage_limit_bytes,
        'storage_usage_percentage': round((total_storage_used / storage_limit_bytes) * 100, 2) if storage_limit_bytes > 0 else 0
    })

class FileViewSet(viewsets.ModelViewSet):
    serializer_class = FileSerializer
    permission_classes = [IsAuthenticated]  # Require authentication

    def get_queryset(self):
        # Start with the user's files
        queryset = File.objects.filter(owner=self.request.user) if self.request.user.is_authenticated else File.objects.none()

        # Get query parameters
        search_query = self.request.query_params.get('search', None)
        file_type = self.request.query_params.get('file_type', None)
        min_size = self.request.query_params.get('min_size', None)
        max_size = self.request.query_params.get('max_size', None)
        start_date = self.request.query_params.get('start_date', None)
        end_date = self.request.query_params.get('end_date', None)

        # Apply search filter
        if search_query is not None:
            queryset = queryset.filter(original_filename__icontains=search_query)

        # Apply file type filter
        if file_type is not None:
            queryset = queryset.filter(file_type__icontains=file_type)

        # Apply size filters
        if min_size is not None:
            try:
                min_size_int = int(min_size)
                queryset = queryset.filter(size__gte=min_size_int)
            except ValueError:
                pass  # Ignore invalid size values

        if max_size is not None:
            try:
                max_size_int = int(max_size)
                queryset = queryset.filter(size__lte=max_size_int)
            except ValueError:
                pass  # Ignore invalid size values

        # Apply date filters
        if start_date is not None:
            from django.utils.dateparse import parse_datetime
            parsed_date = parse_datetime(start_date)
            if parsed_date:
                queryset = queryset.filter(uploaded_at__gte=parsed_date)

        if end_date is not None:
            from django.utils.dateparse import parse_datetime
            parsed_date = parse_datetime(end_date)
            if parsed_date:
                queryset = queryset.filter(uploaded_at__lte=parsed_date)

        return queryset

    def create(self, request, *args, **kwargs):
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'No file provided'}, status=status.HTTP_400_BAD_REQUEST)

        # Get user's storage limit
        try:
            storage_limit_bytes = request.user.profile.storage_limit_mb * 1024 * 1024
        except AttributeError:
            # If profile doesn't exist, create it with default limit
            profile, created = UserProfile.objects.get_or_create(user=request.user, defaults={'storage_limit_mb': 10})
            storage_limit_bytes = profile.storage_limit_mb * 1024 * 1024

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

            # Calculate storage usage considering deduplication
            user_files = File.objects.filter(owner=request.user)
            unique_hashes = {}
            for file in user_files:
                if file.file_hash and file.file_hash not in unique_hashes:
                    unique_hashes[file.file_hash] = file.size
            current_storage_used = sum(unique_hashes.values())

            remaining_storage = storage_limit_bytes - current_storage_used
            response_data = {
                'warning': f'We\'ve processed this upload. A file with the same content already exists as "{existing_file.original_filename}", but this new record is created separately.',
                'file': FileSerializer(new_file_record).data,
                'remaining_storage_bytes': remaining_storage,
                'storage_usage_percentage': round((current_storage_used / storage_limit_bytes) * 100, 2) if storage_limit_bytes > 0 else 0
            }

            # Calculate headers for the new record
            from rest_framework.reverse import reverse
            location = reverse('File-detail', kwargs={'pk': new_file_record.pk}, request=request)
            headers = {'Location': location}

            return Response(response_data, status=status.HTTP_200_OK)

        # Calculate current storage used after deduplication
        user_files = File.objects.filter(owner=request.user)
        unique_hashes = {}
        for file in user_files:
            if file.file_hash and file.file_hash not in unique_hashes:
                unique_hashes[file.file_hash] = file.size
        current_storage_used = sum(unique_hashes.values())

        # Check if the new file would exceed storage quota
        if current_storage_used + file_obj.size > storage_limit_bytes:
            return Response(
                {'error': 'Storage Quota Exceeded'},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

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

        # Calculate remaining storage after successful upload
        new_current_storage = current_storage_used + file_obj.size
        remaining_storage = storage_limit_bytes - new_current_storage

        # Serialize the created record
        serializer = FileSerializer(file_record)

        # Add storage info to the response
        response_data = serializer.data
        response_data['remaining_storage_bytes'] = remaining_storage
        response_data['storage_usage_percentage'] = round((new_current_storage / storage_limit_bytes) * 100, 2) if storage_limit_bytes > 0 else 0

        headers = self.get_success_headers(serializer.data)
        return Response(response_data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        # Only proceed if user is authenticated
        if not self.request.user.is_authenticated:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Authentication required to upload files.")

        # Assign the authenticated user as the owner
        instance = serializer.save(owner=self.request.user)

        # Get the file_hash from the serializer if it exists
        file_hash = getattr(serializer, 'file_hash', None)

        # If we have a file_hash and the instance doesn't have one yet, update it
        if file_hash and not instance.file_hash:
            instance.file_hash = file_hash
            instance.save(update_fields=['file_hash'])
