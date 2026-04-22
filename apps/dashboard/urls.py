from django.urls import path

from apps.dashboard.views import (
    download_patrol_certificate,
    leader_dashboard,
    share_patrol_certificate,
    share_patrol_certificate_telegram,
    stelo_achievement_profile,
    stelo_issue_qr,
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
    # Stelo-Meter public achievement profile (linked from QR)
    path(
        "scouts/achievement/<int:patrol_id>/",
        stelo_achievement_profile,
        name="stelo-achievement-profile",
    ),
    # Authenticated QR issue/renew endpoint
    path("scouts/issue-qr/", stelo_issue_qr, name="stelo-issue-qr"),
]