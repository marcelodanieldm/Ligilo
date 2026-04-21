from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.dashboard.controllers.leader_dashboard_controller import LeaderDashboardController


@login_required
def leader_dashboard(request: HttpRequest) -> HttpResponse:
    controller = LeaderDashboardController()
    return render(request, "ligilo/leader_dashboard.html", controller.get_context())