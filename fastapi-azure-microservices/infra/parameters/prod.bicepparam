using '../main.bicep'

param environmentName = 'prod'
param imageTag = readEnvironmentVariable('IMAGE_TAG', 'latest')
param deployApps = bool(readEnvironmentVariable('DEPLOY_APPS', 'true'))
param postgresAdminPassword = readEnvironmentVariable('POSTGRES_ADMIN_PASSWORD')
param jwtSecret = readEnvironmentVariable('JWT_SECRET')
