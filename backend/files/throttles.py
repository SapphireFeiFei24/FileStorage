from rest_framework.throttling import UserRateThrottle
from .models import UserProfile


class ConfigurableUserRateThrottle(UserRateThrottle):
    """
    Custom throttle class that allows configurable rate limits per user.
    Rate is stored in the user's profile.
    """
    def allow_request(self, request, view):
        """
        Check if the request should be allowed based on the user's rate limit.
        """
        # Get the user from the request
        user = getattr(request, 'user', None)

        if user and user.is_authenticated:
            try:
                # Get the rate from user profile
                profile = user.profile
                # Format: 'x/sec' where x is the number of requests per second
                rate = f"{profile.api_calls_per_second}/sec"

                # Temporarily set the rate for this instance
                self.rate = rate
                self.num_requests, self.duration = self.parse_rate(rate)
            except AttributeError:
                # If profile doesn't exist, use default rate from settings
                pass

        # Call the parent method to perform the actual throttling check
        return super().allow_request(request, view)