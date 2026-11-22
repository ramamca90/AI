// OrderFlow - Azure landing zone for the microservices.
//
//   Internet -> [gateway] (external Container App, HTTPS)
//                  |-> identity-service      (internal)
//                  |-> orders-service        (internal) --outbox--> Service Bus topic
//                  `-> notification-service  (internal) <--subscription--'
//   PostgreSQL Flexible Server (database per service), Key Vault (secrets),
//   ACR (images), Log Analytics + Application Insights (observability).
//   Each app has its own user-assigned managed identity with least privilege.
//
// Deploy:  az deployment group create -g <rg> -f infra/main.bicep -p infra/parameters/dev.bicepparam
targetScope = 'resourceGroup'

@allowed(['dev', 'staging', 'prod'])
param environmentName string = 'dev'
param location string = resourceGroup().location
@maxLength(10)
param namePrefix string = 'orderflow'
@description('Image tag to deploy (git SHA in CI)')
param imageTag string = 'latest'
@description('false on the very first run, before any image has been pushed')
param deployApps bool = true
param postgresAdminLogin string = 'orderflowadmin'
@secure()
param postgresAdminPassword string
@secure()
@minLength(32)
param jwtSecret string

var isProduction = environmentName == 'prod'
var suffix = uniqueString(resourceGroup().id)
var baseName = '${namePrefix}-${environmentName}'
var tags = {
  application: 'orderflow'
  environment: environmentName
  managedBy: 'bicep'
}
var topicName = 'domain-events'

var appNames = ['gateway', 'identity-service', 'orders-service', 'notification-service']
var pythonServices = [
  { name: 'identity-service', database: 'identity', identityIndex: 1, extraEnv: [] }
  { name: 'orders-service', database: 'orders', identityIndex: 2, extraEnv: [] }
  {
    name: 'notification-service'
    database: 'notifications'
    identityIndex: 3
    extraEnv: [{ name: 'EVENT_SUBSCRIPTION', value: 'notification-service' }]
  }
]

// ---------------------------------------------------------------- identity
module identities 'modules/managed-identity.bicep' = [
  for app in appNames: {
    name: 'id-${app}'
    params: { name: 'id-${baseName}-${app}', location: location, tags: tags }
  }
]

// ---------------------------------------------------------------- platform
module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  params: {
    name: baseName
    location: location
    tags: tags
    retentionInDays: isProduction ? 90 : 30
  }
}

module registry 'modules/registry.bicep' = {
  name: 'registry'
  params: {
    name: toLower(replace('acr${namePrefix}${environmentName}${suffix}', '-', ''))
    location: location
    tags: tags
    sku: isProduction ? 'Standard' : 'Basic'
    pullPrincipalIds: [for (app, i) in appNames: identities[i].outputs.principalId]
  }
}

module postgres 'modules/postgres.bicep' = {
  name: 'postgres'
  params: {
    name: 'psql-${baseName}-${take(suffix, 6)}'
    location: location
    tags: tags
    administratorLogin: postgresAdminLogin
    administratorLoginPassword: postgresAdminPassword
    databases: [for svc in pythonServices: svc.database]
    isProduction: isProduction
  }
}

module serviceBus 'modules/servicebus.bicep' = {
  name: 'servicebus'
  params: {
    name: 'sb-${baseName}-${take(suffix, 6)}'
    location: location
    tags: tags
    topicName: topicName
    subscriptions: ['notification-service']
    senderPrincipalIds: [identities[1].outputs.principalId, identities[2].outputs.principalId]
    receiverPrincipalIds: [identities[3].outputs.principalId]
  }
}

var pgUrlPrefix = 'postgresql+asyncpg://${postgresAdminLogin}:${uriComponent(postgresAdminPassword)}@${postgres.outputs.fqdn}:5432/'

module keyVault 'modules/keyvault.bicep' = {
  name: 'keyvault'
  params: {
    name: 'kv${take(replace(namePrefix, '-', ''), 6)}${take(environmentName, 4)}${take(suffix, 8)}'
    location: location
    tags: tags
    enablePurgeProtection: isProduction
    readerPrincipalIds: [for svc in pythonServices: identities[svc.identityIndex].outputs.principalId]
    secrets: {
      'jwt-secret': jwtSecret
      'appinsights-connection-string': monitoring.outputs.appInsightsConnectionString
      'identity-database-url': '${pgUrlPrefix}identity?ssl=require'
      'orders-database-url': '${pgUrlPrefix}orders?ssl=require'
      'notifications-database-url': '${pgUrlPrefix}notifications?ssl=require'
    }
  }
}

module containerEnv 'modules/containerapps-env.bicep' = {
  name: 'containerapps-env'
  params: {
    name: 'cae-${baseName}'
    location: location
    tags: tags
    logAnalyticsWorkspaceName: monitoring.outputs.workspaceName
    zoneRedundant: false
  }
}

// ---------------------------------------------------------------- apps
module services 'modules/containerapp.bicep' = [
  for svc in pythonServices: if (deployApps) {
    name: 'app-${svc.name}'
    params: {
      name: svc.name
      location: location
      tags: tags
      environmentId: containerEnv.outputs.id
      image: '${registry.outputs.loginServer}/${svc.name}:${imageTag}'
      registryServer: registry.outputs.loginServer
      identityId: identities[svc.identityIndex].outputs.id
      external: false
      minReplicas: isProduction ? 2 : 1
      maxReplicas: isProduction ? 10 : 3
      secrets: [
        {
          name: 'jwt-secret'
          keyVaultUrl: '${keyVault.outputs.uri}secrets/jwt-secret'
          identity: identities[svc.identityIndex].outputs.id
        }
        {
          name: 'database-url'
          keyVaultUrl: '${keyVault.outputs.uri}secrets/${svc.database}-database-url'
          identity: identities[svc.identityIndex].outputs.id
        }
        {
          name: 'appinsights-connection-string'
          keyVaultUrl: '${keyVault.outputs.uri}secrets/appinsights-connection-string'
          identity: identities[svc.identityIndex].outputs.id
        }
      ]
      env: concat(
        [
          { name: 'SERVICE_NAME', value: svc.name }
          { name: 'SERVICE_VERSION', value: imageTag }
          { name: 'ENVIRONMENT', value: environmentName }
          { name: 'LOG_LEVEL', value: 'INFO' }
          { name: 'LOG_JSON', value: 'true' }
          { name: 'DOCS_ENABLED', value: isProduction ? 'false' : 'true' }
          { name: 'RUN_MIGRATIONS', value: 'true' }
          { name: 'EVENT_BUS_BACKEND', value: 'azure_servicebus' }
          { name: 'EVENT_TOPIC', value: topicName }
          { name: 'SERVICEBUS_FULLY_QUALIFIED_NAMESPACE', value: serviceBus.outputs.fullyQualifiedNamespace }
          { name: 'AZURE_CLIENT_ID', value: identities[svc.identityIndex].outputs.clientId }
          { name: 'JWT_SECRET', secretRef: 'jwt-secret' }
          { name: 'DATABASE_URL', secretRef: 'database-url' }
          { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', secretRef: 'appinsights-connection-string' }
        ],
        svc.extraEnv
      )
    }
  }
]

module gateway 'modules/containerapp.bicep' = if (deployApps) {
  name: 'app-gateway'
  params: {
    name: 'gateway'
    location: location
    tags: tags
    environmentId: containerEnv.outputs.id
    image: '${registry.outputs.loginServer}/gateway:${imageTag}'
    registryServer: registry.outputs.loginServer
    identityId: identities[0].outputs.id
    external: true
    targetPort: 8080
    cpu: '0.25'
    memory: '0.5Gi'
    minReplicas: isProduction ? 2 : 1
    maxReplicas: isProduction ? 10 : 3
    livenessPath: '/healthz'
    readinessPath: '/healthz'
    // Fully qualified internal names: nginx re-resolves upstreams at runtime
    // with its own resolver, which does not apply DNS search domains.
    env: [
      { name: 'IDENTITY_SERVICE_URL', value: 'http://identity-service.internal.${containerEnv.outputs.defaultDomain}' }
      { name: 'ORDERS_SERVICE_URL', value: 'http://orders-service.internal.${containerEnv.outputs.defaultDomain}' }
      { name: 'NOTIFICATION_SERVICE_URL', value: 'http://notification-service.internal.${containerEnv.outputs.defaultDomain}' }
    ]
  }
  dependsOn: [services]
}

output registryName string = registry.outputs.name
output registryLoginServer string = registry.outputs.loginServer
output keyVaultName string = keyVault.outputs.name
output gatewayUrl string = deployApps ? 'https://${gateway.outputs.fqdn}' : ''
