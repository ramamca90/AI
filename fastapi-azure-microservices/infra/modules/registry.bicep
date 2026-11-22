@description('Globally unique, alphanumeric registry name')
param name string
param location string
param tags object
param sku string = 'Basic'
@description('Principal IDs that may pull images (AcrPull)')
param pullPrincipalIds array

var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: name
  location: location
  tags: tags
  sku: { name: sku }
  properties: {
    adminUserEnabled: false // pulls use managed identity only
  }
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for principalId in pullPrincipalIds: {
    name: guid(registry.id, principalId, acrPullRoleId)
    scope: registry
    properties: {
      principalId: principalId
      principalType: 'ServicePrincipal'
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    }
  }
]

output name string = registry.name
output loginServer string = registry.properties.loginServer
