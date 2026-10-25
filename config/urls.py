from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

admin.site.site_header = f"{settings.COMPANY_NAME} Admin"

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path(
        "login/",
        auth_views.LoginView.as_view(redirect_authenticated_user=True, extra_context={"show_demo": settings.DEMO_MODE}),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("crm.urls")),
]
