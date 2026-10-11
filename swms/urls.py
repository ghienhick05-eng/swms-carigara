from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include, re_path
from django.views.static import serve as media_serve
from django.contrib.auth import views as auth_views
from waste import views as waste_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("register/", waste_views.register, name="register"),
    path("confirm-login/", waste_views.confirm_login_view, name="confirm_login"),
    path("resend-code/", waste_views.resend_code_view, name="resend_code"),
    path("", include("waste.urls")),
]

# Uploaded files (avatars, reports, evidence). django's static.serve is fine at
# this scale; swap for object storage (S3/Cloudinary) if traffic grows.
urlpatterns += [
    re_path(r"^media/(?P<path>.*)$", media_serve, {"document_root": settings.MEDIA_ROOT}),
]