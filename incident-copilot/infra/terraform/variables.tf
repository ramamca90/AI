# --- Identity -------------------------------------------------------------------------------

variable "aws_region" {
  description = "AWS region for every resource."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Prefix for resource names."
  type        = string
  default     = "incident-copilot"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,17}$", var.project_name))
    error_message = "Use 2-18 lowercase letters, digits or hyphens, starting with a letter."
  }
}

variable "environment" {
  description = "Environment name. This module deploys a single environment."
  type        = string
  default     = "demo"

  validation {
    condition     = can(regex("^[a-z0-9]{1,8}$", var.environment))
    error_message = "Use 1-8 lowercase letters or digits (load balancer names are capped at 32 characters)."
  }
}

# --- Network and load balancer --------------------------------------------------------------

variable "vpc_cidr" {
  description = "VPC CIDR. Subnets are carved out of it as /24s."
  type        = string
  default     = "10.40.0.0/16"
}

variable "allowed_ingress_cidrs" {
  description = "CIDRs allowed to reach the ALB. Narrow this to your own IP for a private demo. The deploy smoke test also needs access."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "acm_certificate_arn" {
  description = "ACM certificate ARN. Empty means plain HTTP, which sends the X-API-Key header in clear text. Setting it adds HTTPS and redirects HTTP to HTTPS."
  type        = string
  default     = ""
}

variable "public_hostname" {
  description = "Hostname matching the certificate, if any. You create the DNS record pointing at the ALB. Empty means use the ALB DNS name."
  type        = string
  default     = ""
}

variable "alb_idle_timeout_seconds" {
  description = "ALB idle timeout. Raised from the default of 60 so that quiet SSE streams to the UI stay open."
  type        = number
  default     = 300
}

# --- Application ----------------------------------------------------------------------------

variable "enable_services" {
  description = "Create the ECS services and their autoscaling. Stays false until an image is pushed, the secrets are set and the first migration has run. scripts/deploy.sh flips it."
  type        = bool
  default     = false
}

variable "image_tag" {
  description = "Image tag used in the Terraform-managed task definitions. Deploys register newer revisions outside Terraform."
  type        = string
  default     = "bootstrap"
}

variable "llm_provider" {
  description = "LLM_PROVIDER for the app. `scripted` runs without an Anthropic key. `anthropic` makes the worker require the Anthropic secret."
  type        = string
  default     = "scripted"

  validation {
    condition     = contains(["scripted", "anthropic"], var.llm_provider)
    error_message = "Must be scripted or anthropic."
  }
}

variable "llm_model" {
  description = "LLM_MODEL for the app."
  type        = string
  default     = "claude-opus-5-5"
}

variable "incident_budget_usd" {
  description = "INCIDENT_BUDGET_USD: the LLM spend cap for one incident."
  type        = string
  default     = "2.00"
}

variable "log_level" {
  description = "LOG_LEVEL for the app."
  type        = string
  default     = "INFO"
}

# --- Compute --------------------------------------------------------------------------------

variable "api_cpu" {
  description = "API task CPU units."
  type        = number
  default     = 256
}

variable "api_memory" {
  description = "API task memory in MiB."
  type        = number
  default     = 512
}

variable "worker_cpu" {
  description = "Worker task CPU units. Agents mostly wait on the LLM, so CPU stays small."
  type        = number
  default     = 256
}

variable "worker_memory" {
  description = "Worker task memory in MiB. Larger than the API because one job holds several agent histories."
  type        = number
  default     = 1024
}

variable "api_max_tasks" {
  description = "Upper bound for API autoscaling. The lower bound is 1."
  type        = number
  default     = 3
}

variable "worker_max_tasks" {
  description = "Upper bound for worker autoscaling. The lower bound is 1."
  type        = number
  default     = 3
}

variable "worker_scale_out_queue_depth" {
  description = "Add a worker when this many messages are waiting."
  type        = number
  default     = 5
}

variable "log_retention_days" {
  description = "CloudWatch log retention."
  type        = number
  default     = 14
}

# --- Database -------------------------------------------------------------------------------

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_allocated_storage_gb" {
  description = "RDS storage."
  type        = number
  default     = 20
}

variable "db_backup_retention_days" {
  description = "Automated backup retention. 1 keeps backups on and works on accounts with free-tier limits."
  type        = number
  default     = 1

  validation {
    condition     = var.db_backup_retention_days >= 1
    error_message = "Backups stay on: use at least 1 day."
  }
}

variable "deletion_protection" {
  description = "RDS deletion protection. The default of false lets `terraform destroy` finish right after a demo. Use true for anything you need to keep."
  type        = bool
  default     = false
}

variable "skip_final_snapshot" {
  description = "Skip the final RDS snapshot on destroy. The default of true leaves no snapshot to pay for and loses the data. Use false for anything you need to keep."
  type        = bool
  default     = true
}

# --- Queue ----------------------------------------------------------------------------------

variable "sqs_visibility_timeout_seconds" {
  description = "Must be longer than the longest job (15 minutes), or SQS redelivers a job that is still running. Default is 18 minutes."
  type        = number
  default     = 1080

  validation {
    condition     = var.sqs_visibility_timeout_seconds > 900 && var.sqs_visibility_timeout_seconds <= 43200
    error_message = "Must be more than 900 seconds (the longest job) and at most 43200 (the SQS limit)."
  }
}

# --- Secrets --------------------------------------------------------------------------------

variable "secret_recovery_window_days" {
  description = "Days a deleted secret stays recoverable. 0 deletes at once, so teardown and rebuild can reuse the names. Use 7 or more for anything you need to keep."
  type        = number
  default     = 0
}

# --- Container registry ---------------------------------------------------------------------

variable "ecr_force_delete" {
  description = "Let `terraform destroy` delete the repository even when it holds images."
  type        = bool
  default     = true
}

variable "ecr_keep_images" {
  description = "How many images the ECR lifecycle policy keeps."
  type        = number
  default     = 10
}

# --- Alerts and budget ----------------------------------------------------------------------

variable "alarm_email" {
  description = "Email subscribed to alarms and budget alerts. AWS sends a confirmation link. Empty means no subscription."
  type        = string
  default     = ""
}

variable "monthly_budget_usd" {
  description = "Monthly AWS Budgets limit. The budget covers the whole account, not only this stack."
  type        = number
  default     = 100
}

# --- GitHub Actions -------------------------------------------------------------------------

variable "github_repo" {
  description = "The one repository allowed to deploy, as owner/name. Only its main branch can assume the deploy role."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repo))
    error_message = "Use the form owner/name."
  }
}

variable "create_github_oidc_provider" {
  description = "An AWS account can hold only one GitHub OIDC provider. Set false to reuse an existing one."
  type        = bool
  default     = true
}
