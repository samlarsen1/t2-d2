variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region for all resources"
  type        = string
  default     = "europe-west2"  # London
}

variable "image_tag" {
  description = "Docker image tag to deploy"
  type        = string
  default     = "latest"
}

variable "strategy_mode" {
  description = "Trading strategy mode: mild | moderate | aggressive"
  type        = string
  default     = "mild"

  validation {
    condition     = contains(["mild", "moderate", "aggressive"], var.strategy_mode)
    error_message = "strategy_mode must be mild, moderate, or aggressive"
  }
}

variable "dry_run" {
  description = "If true, no real orders are placed"
  type        = bool
  default     = true
}

variable "t212_base_url" {
  description = "Trading212 API base URL"
  type        = string
  default     = "https://live.trading212.com"
}

variable "fcm_topic" {
  description = "Firebase Cloud Messaging topic for trade push notifications"
  type        = string
  default     = "t2d2-trades"
}

variable "webhook_url" {
  description = "Optional external webhook URL for trade notifications"
  type        = string
  default     = ""
  sensitive   = true
}

variable "alert_email" {
  description = "Email address for Cloud Monitoring alerts"
  type        = string
  default     = ""
}
