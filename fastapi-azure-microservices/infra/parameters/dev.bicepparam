using '../main.bicep'

param environmentName = 'dev'
param imageTag = readEnvironmentVariable('IMAGE_TAG', 'latest')
param deployApps = bool(readEnvironmentVariable('DEPLOY_APPS', 'true'))
// Secrets come from the CI environment (GitHub environment secrets), never the repo.
param postgresAdminPassword = readEnvironmentVariable('POSTGRES_ADMIN_PASSWORD')
param jwtSecret = readEnvironmentVariable('JWT_SECRET')
