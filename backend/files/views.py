from django.shortcuts import render
from rest_framework import viewsets, status
from rest_framework.response import Response
from .models import File
from .serializers import FileSerializer
from io import BytesIO
from django.core.files.uploadedfile import SimpleUploadedFile
import hashlib

# Create your views here.

class FileViewSet(viewsets.ModelViewSet):
    queryset = File.objects.all()
    serializer_class = FileSerializer

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
        # Save the instance first (without file_hash)
        instance = serializer.save()
        # Get the file_hash from the serializer if it exists
        file_hash = getattr(serializer, 'file_hash', None)

        # If we have a file_hash and the instance doesn't have one yet, update it
        if file_hash and not instance.file_hash:
            instance.file_hash = file_hash
            instance.save(update_fields=['file_hash'])
