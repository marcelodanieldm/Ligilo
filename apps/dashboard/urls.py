from django.urls import path

from apps.dashboard.views import (
    download_patrol_certificate,
    leader_dashboard,
    share_patrol_certificate,
    share_patrol_certificate_telegram,
)


app_name = "dashboard"

urlpatterns = [
    path("", leader_dashboard, name="leader-dashboard"),
    path("certificate/download/", download_patrol_certificate, name="download-certificate"),
    path("certificate/share/", share_patrol_certificate, name="share-certificate"),
    path(
        "certificate/share/telegram/",
        share_patrol_certificate_telegram,
        name="share-certificate-telegram",
    ),
]