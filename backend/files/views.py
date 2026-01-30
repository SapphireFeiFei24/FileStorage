from django.shortcuts import render
from django.contrib.auth import authenticate, login, logout
from rest_framework import viewsets, status, views
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.decorators import api_view, permission_classes
from .models import File
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
    }
    return Response(content)

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

        # Calculate hash of the incoming file to check for duplicates
        sha256_hash = hashlib.sha256()

        # Read the file in chunks to calculate hash and store content temporarily
        file_content = BytesIO()
        for chunk in file_obj.chunks():
            sha256_hash.update(chunk)
            file_content.write(chunk)

        file_hash = sha256_hash.hexdigest()

        # Check if a file with the same hash already exists
        existing_file = File.objects.filter(file_hash=file_hash).first()
        if existing_file:
            # Return a warning response with the existing file info
            response_data = {
                'warning': f'We\'ve processed this upload, but the same file already exists as "{existing_file.original_filename}". No duplicate was stored.',
                'existing_file': FileSerializer(existing_file).data
            }
            return Response(response_data, status=status.HTTP_200_OK)

        # Reset the file pointer to the beginning for saving
        file_content.seek(0)

        # Create a new file-like object with the content we stored
        new_file_obj = SimpleUploadedFile(
            name=file_obj.name,
            content=file_content.getvalue(),
            content_type=file_obj.content_type
        )

        # Store the file_hash in the serializer context so perform_create can access it
        data = {
            'file': new_file_obj,
            'original_filename': file_obj.name,
            'file_type': file_obj.content_type,
            'size': file_obj.size
        }

        serializer = self.get_serializer(data=data)

        try:
            serializer.is_valid(raise_exception=True)
            # Pass the file_hash to the serializer context
            serializer.file_hash = file_hash
            self.perform_create(serializer)

            headers = self.get_success_headers(serializer.data)
            return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)
        except Exception as e:
            # Handle other potential errors
            import traceback
            print(traceback.format_exc())
            return Response({'error': 'An error occurred while processing the file'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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
