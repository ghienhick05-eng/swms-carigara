from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q

User = get_user_model()


class EmailOrUsernameBackend(ModelBackend):
    """
    Authenticates against either the username or the email address, so a
    user can log in with whichever one they type into the "Username"
    field on the login form.

    Falls back to the default ModelBackend behaviour in every other
    respect (password hashing, is_active checks, permission caching).
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(User.USERNAME_FIELD)
        if username is None or password is None:
            return None

        try:
            user = User.objects.get(
                Q(username__iexact=username) | Q(email__iexact=username)
            )
        except User.DoesNotExist:
            # Run the hasher anyway to avoid leaking, via response timing,
            # whether a given username/email exists in the system.
            User().set_password(password)
            return None
        except User.MultipleObjectsReturned:
            # Shouldn't happen since both fields are unique, but if it
            # ever does, prefer an exact username match.
            user = User.objects.filter(username__iexact=username).first()
            if user is None:
                return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None