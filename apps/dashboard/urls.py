from django.urls import path

from apps.dashboard.views import (
    download_patrol_certificate,
    leader_dashboard,
    patrol_onboarding_step_a,
    patrol_onboarding_step_b,
    patrol_onboarding_step_c,
    patrol_operations_dashboard,
    share_patrol_certificate,
    share_patrol_certificate_telegram,
    stelo_achievement_profile,
    stelo_issue_qr,
    youtube_submission_review,
)


app_name = "dashboard"

urlpatterns = [
    path("", leader_dashboard, name="leader-dashboard"),
    path(
        "patrol/onboarding/<uuid:token>/step-a/",
        patrol_onboarding_step_a,
        name="patrol-onboarding-step-a",
    ),
    path(
        "patrol/onboarding/<uuid:token>/step-b/",
        patrol_onboarding_step_b,
        name="patrol-onboarding-step-b",
    ),
    path(
        "patrol/onboarding/<uuid:token>/step-c/",
        patrol_onboarding_step_c,
        name="patrol-onboarding-step-c",
    ),
    path(
        "patrol/operations/<uuid:token>/",
        patrol_operations_dashboard,
        name="patrol-operations",
    ),
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
    # Human final approval for AI-validated YouTube submissions
    path(
        "scouts/youtube/review/<int:submission_id>/",
        youtube_submission_review,
        name="youtube-review",
    ),
]