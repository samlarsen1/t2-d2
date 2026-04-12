output "cloud_run_job_name" {
  value       = google_cloud_run_v2_job.t2d2_scheduler.name
  description = "Cloud Run Job name"
}

output "artifact_registry_repo" {
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/t2d2"
  description = "Docker image push target"
}

output "scheduler_jobs" {
  value       = { for k, v in google_cloud_scheduler_job.t2d2_sessions : k => v.schedule }
  description = "Configured scheduler jobs and their cron schedules"
}

output "runner_service_account" {
  value       = google_service_account.t2d2_runner.email
  description = "Service account email used by Cloud Run jobs"
}
