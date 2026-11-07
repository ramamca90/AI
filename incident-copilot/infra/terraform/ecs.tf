resource "aws_ecs_cluster" "main" {
  name = local.name

  setting {
    name  = "containerInsights"
    value = "disabled" # Costs extra. The app already exports /metrics.
  }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = ["FARGATE"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${local.name}/api"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/${local.name}/worker"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "migrate" {
  name              = "/ecs/${local.name}/migrate"
  retention_in_days = var.log_retention_days
}

locals {
  image = "${aws_ecr_repository.app.repository_url}:${var.image_tag}"

  app_environment = [
    { name = "AWS_REGION", value = var.aws_region },
    { name = "INCIDENT_BUDGET_USD", value = var.incident_budget_usd },
    { name = "LLM_MODEL", value = var.llm_model },
    { name = "LLM_PROVIDER", value = var.llm_provider },
    { name = "LOG_LEVEL", value = var.log_level },
    { name = "QUEUE_BACKEND", value = "sqs" },
    { name = "SQS_QUEUE_URL", value = aws_sqs_queue.jobs.url },
  ]

  database_url_secret = {
    name      = "DATABASE_URL"
    valueFrom = aws_secretsmanager_secret.database_url.arn
  }

  # With the scripted provider the Anthropic secret can stay empty, so it is left out entirely.
  anthropic_secrets = var.llm_provider == "anthropic" ? [{
    name      = "ANTHROPIC_API_KEY"
    valueFrom = aws_secretsmanager_secret.anthropic_api_key.arn
  }] : []
}

# --- Task definitions -----------------------------------------------------------------------
#
# These are the base revisions. scripts/deploy.sh copies the latest revision of each family with
# a new image tag, so Terraform changes (such as environment variables) go live on the next
# deploy.

resource "aws_ecs_task_definition" "api" {
  family                   = local.api_family
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = aws_iam_role.execution["api"].arn
  task_role_arn            = aws_iam_role.api_task.arn

  container_definitions = jsonencode([{
    name         = "api"
    image        = local.image
    essential    = true
    command      = ["copilot-api"]
    portMappings = [{ containerPort = 8000, protocol = "tcp" }]
    environment  = local.app_environment
    secrets = [
      { name = "API_KEY", valueFrom = aws_secretsmanager_secret.api_key.arn },
      local.database_url_secret,
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.api.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "api"
      }
    }
  }])
}

resource "aws_ecs_task_definition" "worker" {
  family                   = local.worker_family
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.worker_cpu
  memory                   = var.worker_memory
  execution_role_arn       = aws_iam_role.execution["worker"].arn
  task_role_arn            = aws_iam_role.worker_task.arn

  container_definitions = jsonencode([{
    name        = "worker"
    image       = local.image
    essential   = true
    command     = ["copilot-worker"]
    stopTimeout = 120 # The Fargate maximum. Jobs still running after this are redelivered by SQS.
    environment = local.app_environment
    secrets     = concat([local.database_url_secret], local.anthropic_secrets)
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.worker.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "worker"
      }
    }
  }])
}

# One-off: never attached to a service. It runs in the worker security group for database access,
# and has no task role because migrations call no AWS API.
resource "aws_ecs_task_definition" "migrate" {
  family                   = local.migrate_family
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution["migrate"].arn

  container_definitions = jsonencode([{
    name        = "migrate"
    image       = local.image
    essential   = true
    command     = ["alembic", "upgrade", "head"]
    environment = local.app_environment
    secrets     = [local.database_url_secret]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.migrate.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "migrate"
      }
    }
  }])
}

# --- Services -------------------------------------------------------------------------------
#
# task_definition is ignored because deploys move it, and desired_count because autoscaling does.

resource "aws_ecs_service" "api" {
  count = local.services_count

  name            = local.api_service_name
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 1
  launch_type     = "FARGATE"
  propagate_tags  = "SERVICE"

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = 60

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.api.id]
    assign_public_ip = true # Needed without NAT. Inbound is still limited to the ALB.
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.http, aws_lb_listener.https]

  lifecycle {
    ignore_changes = [task_definition, desired_count]

    precondition {
      condition     = var.image_tag != "bootstrap"
      error_message = "Set image_tag to a pushed image before enabling services. scripts/deploy.sh does this."
    }
  }
}

resource "aws_ecs_service" "worker" {
  count = local.services_count

  name            = local.worker_service_name
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = 1
  launch_type     = "FARGATE"
  propagate_tags  = "SERVICE"

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.worker.id]
    assign_public_ip = true
  }

  lifecycle {
    ignore_changes = [task_definition, desired_count]

    precondition {
      condition     = var.image_tag != "bootstrap"
      error_message = "Set image_tag to a pushed image before enabling services. scripts/deploy.sh does this."
    }
  }
}
