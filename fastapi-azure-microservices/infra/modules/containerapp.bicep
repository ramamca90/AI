@description('Container App name; also its DNS name inside the environment')
param name string
param location string
param tags object
param environmentId string
param image string
param registryServer string
param identityId string
@description('true = internet-facing; false = reachable only inside the environment')
param external bool = false
param targetPort int = 8000
param env array = []
@description('Container Apps secrets, typically Key Vault references')
param secrets array = []
param cpu string = '0.5'
param memory string = '1Gi'
param minReplicas int = 1
param maxReplicas int = 5
param livenessPath string = '/health/live'
param readinessPath string = '/health/ready'
param scaleRules array = [
  { name: 'http-concurrency', http: { metadata: { concurrentRequests: '50' } } }
]

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identityId}': {} }
  }
  properties: {
    managedEnvironmentId: environmentId
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: external
        targetPort: targetPort
        transport: 'auto'
        allowInsecure: !external // internal hops stay inside the environment
      }
      registries: [
        { server: registryServer, identity: identityId }
      ]
      secrets: secrets
    }
    template: {
      containers: [
        {
          name: name
          image: image
          resources: { cpu: json(cpu), memory: memory }
          env: env
          probes: [
            {
              type: 'Startup'
              httpGet: { path: livenessPath, port: targetPort }
              periodSeconds: 5
              failureThreshold: 24 // allow up to 2 min for migrations
            }
            {
              type: 'Liveness'
              httpGet: { path: livenessPath, port: targetPort }
              periodSeconds: 15
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: { path: readinessPath, port: targetPort }
              periodSeconds: 10
              failureThreshold: 3
            }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
        rules: scaleRules
      }
    }
  }
}

output fqdn string = app.properties.configuration.ingress.fqdn
