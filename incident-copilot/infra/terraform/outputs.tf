output "name_prefix" {
  description = "Prefix of every resource name."
  value       = local.name
}

output "aws_region" {
  description = "Deployment region."
  value       = var.aws_region
}

output "base_url" {
  description = "Public URL of the API."
  value       = local.public_url
}

output "ecr_repository_url" {
  description = "Repository to push images to."
  value       = aws_ecr_repository.app.repository_url
}

output "ecs_cluster_name" {
  description = "ECS cluster."
  value       = aws_ecs_cluster.main.name
}

output "api_service_name" {
  description = "API service name. It exists once enable_services is true."
  value       = local.api_service_name
}

output "worker_service_name" {
  description = "Worker service name. It exists once enable_services is true."
  value       = local.worker_service_name
}

output "api_task_family" {
  description = "API task definition family."
  value       = local.api_family
}

output "worker_task_family" {
  description = "Worker task definition family."
  value       = local.worker_family
}

output "migrate_task_family" {
  description = "Migration task definition family."
  value       = local.migrate_family
}

output "migrate_subnets" {
  description = "Comma-separated subnets for the migration task."
  value       = join(",", aws_subnet.public[*].id)
}

output "migrate_security_group" {
  description = "Security group for the migration task."
  value       = aws_security_group.worker.id
}

output "anthropic_api_key_secret_name" {
  description = "Secret to fill with scripts/set-secrets.sh anthropic."
  value       = aws_secretsmanager_secret.anthropic_api_key.name
}

output "api_key_secret_name" {
  description = "Secret to fill with scripts/set-secrets.sh api-key."
  value       = aws_secretsmanager_secret.api_key.name
}

output "llm_provider" {
  description = "LLM provider the tasks run with."
  value       = var.llm_provider
}

output "sqs_queue_url" {
  description = "Jobs queue."
  value       = aws_sqs_queue.jobs.url
}

output "sqs_dlq_url" {
  description = "Dead-letter queue."
  value       = aws_sqs_queue.dlq.url
}

output "rds_address" {
  description = "Database host, reachable only from inside the VPC."
  value       = aws_db_instance.main.address
}

output "github_deploy_role_arn" {
  description = "Role assumed by .github/workflows/deploy.yml."
  value       = aws_iam_role.github_deploy.arn
}

output "github_actions_variables" {
  description = "Repository variables that deploy.yml needs. None of them is a secret."
  value = {
    AWS_DEPLOY_ROLE_ARN    = aws_iam_role.github_deploy.arn
    AWS_REGION             = var.aws_region
    BASE_URL               = local.public_url
    ECR_REPOSITORY_URL     = aws_ecr_repository.app.repository_url
    ECS_CLUSTER            = aws_ecs_cluster.main.name
    API_SERVICE            = local.api_service_name
    WORKER_SERVICE         = local.worker_service_name
    API_TASK_FAMILY        = local.api_family
    WORKER_TASK_FAMILY     = local.worker_family
    MIGRATE_TASK_FAMILY    = local.migrate_family
    MIGRATE_SUBNETS        = join(",", aws_subnet.public[*].id)
    MIGRATE_SECURITY_GROUP = aws_security_group.worker.id
  }
}
