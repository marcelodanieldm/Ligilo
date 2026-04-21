from django.urls import path

from apps.dashboard.views import leader_dashboard


app_name = "dashboard"

urlpatterns = [
    path("", leader_dashboard, name="leader-dashboard"),
]