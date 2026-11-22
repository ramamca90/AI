param name string
param location string
param tags object
param enablePurgeProtection bool
@description('Principal IDs granted "Key Vault Secrets User" (read secret values)')
param readerPrincipalIds array
@secure()
@description('Secret name -> value map written to the vault')
param secrets object

var secretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true // no access policies; Azure RBAC only
    enableSoftDelete: true
    softDeleteRetentionInDays: 30
    enablePurgeProtection: enablePurgeProtection ? true : null
    publicNetworkAccess: 'Enabled'
  }
}

resource vaultSecrets 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = [
  for item in items(secrets): {
    parent: vault
    name: item.key
    properties: { value: item.value }
  }
]

resource secretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for principalId in readerPrincipalIds: {
    name: guid(vault.id, principalId, secretsUserRoleId)
    scope: vault
    properties: {
      principalId: principalId
      principalType: 'ServicePrincipal'
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', secretsUserRoleId)
    }
  }
]

output name string = vault.name
output uri string = vault.properties.vaultUri
