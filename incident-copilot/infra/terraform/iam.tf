data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# --- Execution roles: used by ECS itself to pull the image, write logs and fetch secrets -----
#
# Secret values are injected by these roles, not read by the app, so the task roles below hold
# no Secrets Manager permissions at all. Each workload gets only the secrets it receives.

locals {
  execution_roles = {
    api = {
      log_group = aws_cloudwatch_log_group.api.arn
      secrets   = [aws_secretsmanager_secret.database_url.arn, aws_secretsmanager_secret.api_key.arn]
    }
    worker = {
      log_group = aws_cloudwatch_log_group.worker.arn
      secrets = concat(
        [aws_secretsmanager_secret.database_url.arn],
        var.llm_provider == "anthropic" ? [aws_secretsmanager_secret.anthropic_api_key.arn] : [],
      )
    }
    migrate = {
      log_group = aws_cloudwatch_log_group.migrate.arn
      secrets   = [aws_secretsmanager_secret.database_url.arn]
    }
  }
}

resource "aws_iam_role" "execution" {
  for_each = local.execution_roles

  name               = "${local.name}-${each.key}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

data "aws_iam_policy_document" "execution" {
  for_each = local.execution_roles

  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # This action does not support resource scoping.
  }

  statement {
    sid = "EcrPull"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [aws_ecr_repository.app.arn]
  }

  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${each.value.log_group}:*"]
  }

  statement {
    sid       = "Secrets"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = each.value.secrets
  }
}

resource "aws_iam_role_policy" "execution" {
  for_each = local.execution_roles

  name   = "execution"
  role   = aws_iam_role.execution[each.key].id
  policy = data.aws_iam_policy_document.execution[each.key].json
}

# --- Task roles: what the running app can do ------------------------------------------------

resource "aws_iam_role" "api_task" {
  name               = "${local.name}-api-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

data "aws_iam_policy_document" "api_task" {
  statement {
    sid       = "EnqueueJobs"
    actions   = ["sqs:SendMessage", "sqs:GetQueueAttributes", "sqs:GetQueueUrl"]
    resources = [aws_sqs_queue.jobs.arn]
  }
}

resource "aws_iam_role_policy" "api_task" {
  name   = "queue-producer"
  role   = aws_iam_role.api_task.id
  policy = data.aws_iam_policy_document.api_task.json
}

resource "aws_iam_role" "worker_task" {
  name               = "${local.name}-worker-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

data "aws_iam_policy_document" "worker_task" {
  # SendMessage is here because the worker's sweeper re-enqueues jobs that were lost.
  statement {
    sid = "ConsumeJobs"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:SendMessage",
      "sqs:ChangeMessageVisibility",
      "sqs:GetQueueAttributes",
      "sqs:GetQueueUrl",
    ]
    resources = [aws_sqs_queue.jobs.arn]
  }
}

resource "aws_iam_role_policy" "worker_task" {
  name   = "queue-consumer"
  role   = aws_iam_role.worker_task.id
  policy = data.aws_iam_policy_document.worker_task.json
}
