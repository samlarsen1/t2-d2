# Cloud Scheduler jobs — one per trading session
# Each overrides the container args to pass the correct --session flag.

locals {
  sessions = {
    eu_morning = {
      schedule    = "30 7 * * 1-5"
      description = "EU/London market open (08:30 GMT / 09:30 CET)"
      session_arg = "eu_morning"
    }
    eu_afternoon = {
      schedule    = "0 13 * * 1-5"
      description = "EU mid-session rebalance (14:00 BST / 15:00 CET)"
      session_arg = "eu_afternoon"
    }
    us_morning = {
      schedule    = "30 14 * * 1-5"
      description = "NYSE/NASDAQ open (09:30 ET)"
      session_arg = "us_morning"
    }
    us_afternoon = {
      schedule    = "30 18 * * 1-5"
      description = "US afternoon session (13:30 ET)"
      session_arg = "us_afternoon"
    }
    daily_close_wrap = {
      schedule    = "0 21 * * 1-5"
      description = "End-of-day summary (17:00 ET)"
      session_arg = "daily_close_wrap"
    }
  }
}

resource "google_cloud_scheduler_job" "t2d2_sessions" {
  for_each = local.sessions

  name             = "t2d2-${each.key}"
  description      = each.value.description
  schedule         = each.value.schedule
  time_zone        = "UTC"
  attempt_deadline = "660s"  # Slightly longer than job timeout

  retry_config {
    retry_count          = 1
    max_retry_duration   = "600s"
    min_backoff_duration = "60s"
    max_doublings        = 2
  }

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/t2d2-scheduler:run"

    body = base64encode(jsonencode({
      overrides = {
        containerOverrides = [
          {
            args = ["--session", each.value.session_arg]
          }
        ]
      }
    }))

    headers = {
      "Content-Type" = "application/json"
    }

    oauth_token {
      service_account_email = google_service_account.t2d2_scheduler.email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  depends_on = [
    google_project_service.apis,
    google_cloud_run_v2_job.t2d2_scheduler,
  ]
}
