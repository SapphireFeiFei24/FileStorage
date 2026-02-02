from django.contrib.auth.models import AnonymousUser
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from django.contrib.auth import get_user_model

User = get_user_model()


class UserIdHeaderAuthentication(BaseAuthentication):
    """
    Custom authentication that reads user ID from a header named 'UserId'.
    """
    def authenticate(self, request):
        user_id = request.META.get('HTTP_USERID') or request.META.get('HTTP_USER_ID')
        
        if not user_id:
            # If no UserId header is provided, return None to continue with other authentication methods
            # or return AnonymousUser if you want to enforce this method
            return None
        
        try:
            user_id = int(user_id)
            user = User.objects.get(id=user_id)
            return (user, None)
        except (ValueError, User.DoesNotExist):
            raise AuthenticationFailed('Invalid UserId header provided.')
    
    def authenticate_header(self, request):
        return 'UserId'